"""Phase 14: webhooks - management API, secrets, SSRF rules, signing, delivery and retries,
and events from real flows."""

import json
import socket
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.developer.secrets import hash_secret, sign, webhook_secret
from app.developer.webhooks import EVENTS, emit, ssrf, verify_signature
from app.developer.webhooks import delivery as delivery_module
from app.developer.webhooks.signature import signature_header
from app.models import Organization, OrganizationMember, User, WebhookDelivery, WebhookEndpoint
from tests.conftest import USER

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
URL = "https://hooks.example.com/ahc"
PUBLIC_IP = "93.184.216.34"
CLONE = {
    "name": "Ayaan AI",
    "bio": "Software developer",
    "profession": "Software Developer",
    "skills": ["Python"],
    "response_length": "short",
    "owner_consent": True,
}
DNS = {
    "hooks.example.com": [PUBLIC_IP],
    "other.example.com": ["93.184.216.35"],
    "v6.example.com": ["2606:2800:220:1:248:1893:25c8:1946"],
    "rebind.example.com": ["10.0.0.5"],
    "mixed.example.com": [PUBLIC_IP, "127.0.0.1"],
    "metadata-alias.example.com": ["169.254.169.254"],
}


@pytest.fixture(autouse=True)
def webhook_env(monkeypatch, db_session: Session):
    """Deliveries use the test database, fake DNS, and run on the calling thread."""
    monkeypatch.setattr(delivery_module, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(delivery_module, "INLINE", False)
    monkeypatch.setattr(delivery_module, "SYNC_WRITE", True)
    monkeypatch.setattr(delivery_module, "CONCURRENCY", 1)
    monkeypatch.setattr(delivery_module, "TRANSPORT", None)
    dns = dict(DNS)

    def fake_resolve(host: str, port: int) -> list[str]:
        if host not in dns:
            raise socket.gaierror("not found")
        return dns[host]

    monkeypatch.setattr(ssrf, "resolve_host", fake_resolve)
    delivery_module.reset_dedupe()
    delivery_module.clear_events()
    yield dns
    delivery_module.clear_events()


class Receiver:
    """An httpx MockTransport that records requests and answers from a script."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses) or [200]
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        action = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(action, Exception):
            raise action
        if isinstance(action, int):
            headers = {"Location": "https://elsewhere.example.com/"} if 300 <= action < 400 else {}
            return httpx.Response(action, headers=headers, text="ok")
        return action

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def sara(make_client) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=SARA).status_code == 201
    return browser


def make_hook(client: TestClient, events=("clone.created",), url: str = URL, **extra) -> dict:
    response = client.post("/api/developer/webhooks", json={"url": url, "events": list(events), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def user_id(db: Session, email: str):
    return db.scalar(select(User.id).where(User.email == email.lower()))


def make_org(db: Session, owner_email: str, member_email: str | None = None, role: str = "member") -> Organization:
    owner = db.scalar(select(User).where(User.email == owner_email.lower()))
    org = Organization(name="Acme", slug="acme", owner_id=owner.id, is_active=True)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner", status="active"))
    if member_email:
        member = db.scalar(select(User).where(User.email == member_email.lower()))
        db.add(OrganizationMember(organization_id=org.id, user_id=member.id, role=role, status="active"))
    db.commit()
    return org


def deliveries(db: Session, **filters) -> list[WebhookDelivery]:
    db.expire_all()
    query = select(WebhookDelivery).order_by(WebhookDelivery.created_at)
    for key, value in filters.items():
        query = query.where(getattr(WebhookDelivery, key) == value)
    return list(db.scalars(query))


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# --- Management API -------------------------------------------------------------


def test_events_catalog(owner: TestClient) -> None:
    events = owner.get("/api/developer/webhooks/events").json()
    assert [e["event"] for e in events] == list(EVENTS)
    assert all(e["description"] for e in events)


def test_create_list_get_patch_delete(owner: TestClient) -> None:
    created = make_hook(owner, events=("clone.created", "message.completed"))
    assert created["secret"].startswith("whsec_")
    assert created["owner_type"] == "user" and created["organization_id"] is None
    assert created["is_active"] is True and created["failure_count"] == 0
    assert created["url"] == URL and created["events"] == ["clone.created", "message.completed"]
    hook_id = created["id"]

    listed = owner.get("/api/developer/webhooks").json()
    assert [h["id"] for h in listed] == [hook_id] and "secret" not in listed[0]
    got = owner.get(f"/api/developer/webhooks/{hook_id}").json()
    assert "secret" not in got and got["id"] == hook_id
    assert set(got) == {
        "id", "url", "events", "is_active", "owner_type", "organization_id",
        "failure_count", "last_delivery_at", "created_at", "updated_at",
    }

    patched = owner.patch(
        f"/api/developer/webhooks/{hook_id}",
        json={"url": "https://other.example.com/x", "events": ["voice.completed"], "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["url"] == "https://other.example.com/x" and body["events"] == ["voice.completed"]
    assert body["is_active"] is False and "secret" not in body

    assert owner.patch(f"/api/developer/webhooks/{hook_id}", json={"url": "https://127.0.0.1/"}).status_code == 400
    assert owner.patch(f"/api/developer/webhooks/{hook_id}", json={"events": []}).status_code == 400
    assert owner.delete(f"/api/developer/webhooks/{hook_id}").status_code == 204
    assert owner.get(f"/api/developer/webhooks/{hook_id}").status_code == 404
    assert owner.get("/api/developer/webhooks").json() == []


def test_events_must_be_known_and_present(owner: TestClient) -> None:
    post = lambda body: owner.post("/api/developer/webhooks", json=body).status_code  # noqa: E731
    assert post({"url": URL, "events": []}) == 400
    assert post({"url": URL, "events": ["clone.deleted"]}) == 400
    assert post({"url": URL, "events": ["webhook.test"]}) == 400  # test events can't be subscribed
    assert post({"url": URL}) == 400
    assert post({"url": URL, "events": ["clone.created"], "secret": "mine"}) == 400
    assert post({"url": URL, "events": ["clone.created", "clone.created"]}) == 201


def test_login_required(client: TestClient) -> None:
    assert client.get("/api/developer/webhooks").status_code == 401
    assert client.post("/api/developer/webhooks", json={"url": URL, "events": ["clone.created"]}).status_code == 401


def test_secret_shown_once_and_never_stored(owner: TestClient, db_session: Session) -> None:
    created = make_hook(owner)
    secret = created["secret"]
    row = db_session.scalar(select(WebhookEndpoint))
    stored = " ".join(str(getattr(row, column.name)) for column in WebhookEndpoint.__table__.columns)
    assert secret not in stored and secret[6:] not in stored
    assert row.secret_hash == hash_secret(secret)
    assert webhook_secret(row.id, row.secret_salt) == secret  # re-derived on the server
    for response in (owner.get("/api/developer/webhooks"), owner.get(f"/api/developer/webhooks/{created['id']}")):
        assert secret not in response.text and "whsec_" not in response.text and '"secret"' not in response.text


def test_rotate_secret(owner: TestClient, db_session: Session) -> None:
    created = make_hook(owner)
    rotated = owner.post(f"/api/developer/webhooks/{created['id']}/rotate-secret")
    assert rotated.status_code == 200, rotated.text
    new_secret = rotated.json()["secret"]
    assert new_secret.startswith("whsec_") and new_secret != created["secret"]
    assert rotated.json()["id"] == created["id"]
    row = db_session.scalar(select(WebhookEndpoint))
    db_session.refresh(row)
    assert row.secret_hash == hash_secret(new_secret) and webhook_secret(row.id, row.secret_salt) == new_secret

    receiver = Receiver(200)
    emit("clone.created", {"clone_id": "c1"}, user_id=row.user_id)
    delivery_module.process_due(transport=receiver.transport)
    request = receiver.requests[0]
    header = request.headers["X-AHC-Signature"]
    assert verify_signature(new_secret, header, request.content)
    assert not verify_signature(created["secret"], header, request.content)  # the old secret stopped


def test_other_users_get_404(owner: TestClient, sara: TestClient, db_session: Session) -> None:
    hook = make_hook(owner)
    hook_id = hook["id"]
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    delivery_id = deliveries(db_session)[0].id
    base = f"/api/developer/webhooks/{hook_id}"
    assert sara.get(base).status_code == 404
    assert sara.patch(base, json={"is_active": False}).status_code == 404
    assert sara.delete(base).status_code == 404
    assert sara.post(f"{base}/rotate-secret").status_code == 404
    assert sara.post(f"{base}/test").status_code == 404
    assert sara.get(f"{base}/deliveries").status_code == 404
    assert sara.post(f"{base}/deliveries/{delivery_id}/retry").status_code == 404
    assert sara.get("/api/developer/webhooks").json() == []
    assert owner.get(base).status_code == 200


def test_organization_webhooks_owner_and_admin_only(
    owner: TestClient, sara: TestClient, make_client, db_session: Session
) -> None:
    org = make_org(db_session, USER["email"], SARA["email"], role="member")
    created = make_hook(owner, organization_id=str(org.id))
    assert created["owner_type"] == "organization" and created["organization_id"] == str(org.id)
    row = db_session.get(WebhookEndpoint, __import__("uuid").UUID(created["id"]))
    assert row.user_id is None and row.organization_id == org.id

    # A plain member can't create, see or manage the organization's webhooks.
    assert sara.post(
        "/api/developer/webhooks", json={"url": URL, "events": ["clone.created"], "organization_id": str(org.id)}
    ).status_code == 403
    assert sara.get("/api/developer/webhooks").json() == []
    assert sara.get(f"/api/developer/webhooks/{created['id']}").status_code == 404

    # Promoted to admin: now they can.
    member = db_session.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user_id(db_session, SARA["email"])))
    member.role = "admin"
    db_session.commit()
    assert [h["id"] for h in sara.get("/api/developer/webhooks").json()] == [created["id"]]
    assert sara.patch(f"/api/developer/webhooks/{created['id']}", json={"is_active": False}).status_code == 200

    # Organization events reach the organization's webhooks.
    owner.patch(f"/api/developer/webhooks/{created['id']}", json={"is_active": True})
    emit("clone.created", {"clone_id": "c1"}, organization_id=org.id)
    assert len(deliveries(db_session, webhook_id=row.id)) == 1


# --- SSRF -----------------------------------------------------------------------

BAD_URLS = [
    "http://127.0.0.1/hook",
    "https://127.0.0.1/hook",
    "https://localhost/hook",
    "https://localhost./hook",
    "https://api.localhost/hook",
    "https://[::1]/hook",
    "https://0.0.0.0/hook",
    "https://10.1.2.3/hook",
    "https://172.16.5.4/hook",
    "https://172.31.255.255/hook",
    "https://192.168.1.10/hook",
    "https://[fc00::1]/hook",
    "https://[fd12:3456::1]/hook",
    "https://169.254.169.254/latest/meta-data/",
    "https://[fe80::1]/hook",
    "https://metadata.google.internal/computeMetadata/v1/",
    "https://metadata/hook",
    "https://db.internal/hook",
    "https://printer.local/hook",
    "https://100.64.0.1/hook",
    "https://224.0.0.1/hook",
    "https://240.0.0.1/hook",
    "https://255.255.255.255/hook",
    "https://[ff02::1]/hook",
    "https://[::ffff:127.0.0.1]/hook",
    "https://[::ffff:a9fe:a9fe]/hook",
    "https://[64:ff9b::7f00:1]/hook",
    "https://[2002:7f00:1::]/hook",
    "https://[::127.0.0.1]/hook",
    "https://2130706433/hook",
    "https://0x7f000001/hook",
    "https://0x7f.0.0.1/hook",
    "https://0177.0.0.1/hook",
    "https://017700000001/hook",
    "https://127.1/hook",
    "https://127.000.000.001/hook",
    "https://user:pass@hooks.example.com/hook",
    "https://hooks.example.com@127.0.0.1/hook",
    "https://:@hooks.example.com/hook",
    "ftp://hooks.example.com/hook",
    "file:///etc/passwd",
    "gopher://hooks.example.com/",
    "javascript:alert(1)",
    "hooks.example.com/hook",
    "//hooks.example.com/hook",
    "https:///hook",
    "https://redis/hook",
    "https://rebind.example.com/hook",
    "https://mixed.example.com/hook",
    "https://metadata-alias.example.com/hook",
    "https://does-not-exist.example.org/hook",
    "https://hooks.example.com:0/hook",
    "https://hooks.example.com:99999/hook",
    "https://hooks.example.com/hook#frag",
    "https://hooks.example.com/a b",
    "https://hooks.example.com\\@127.0.0.1/",
    "https://[fe80::1%25eth0]/hook",
    "https://" + "a" * 2000 + ".example.com/",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_ssrf_rejected(url: str) -> None:
    with pytest.raises(ssrf.WebhookUrlError):
        ssrf.validate_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://127.0.0.1/hook", "https://169.254.169.254/", "https://rebind.example.com/", "ftp://hooks.example.com/"],
)
def test_ssrf_rejected_by_api(owner: TestClient, url: str) -> None:
    response = owner.post("/api/developer/webhooks", json={"url": url, "events": ["clone.created"]})
    assert response.status_code == 400
    assert response.json()


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/ahc",
        "https://hooks.example.com:8443/ahc?x=1",
        "https://HOOKS.example.com/ahc",
        "https://v6.example.com/",
        "https://93.184.216.34/hook",
        "http://hooks.example.com/dev-only",
    ],
)
def test_public_urls_accepted(url: str) -> None:
    assert ssrf.validate_url(url).startswith(url.split(":")[0])


def test_http_only_outside_production(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "environment", "production")
    with pytest.raises(ssrf.WebhookUrlError):
        ssrf.validate_url("http://hooks.example.com/hook")
    assert ssrf.validate_url("https://hooks.example.com/hook")


def test_dns_rebinding_blocked_at_delivery(owner: TestClient, db_session: Session, webhook_env: dict) -> None:
    make_hook(owner)
    webhook_env["hooks.example.com"] = ["127.0.0.1"]  # the name now points inside
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    receiver = Receiver(200)
    delivery_module.process_due(transport=receiver.transport)
    row = deliveries(db_session)[0]
    assert receiver.requests == []
    assert row.status == "pending" and row.attempts == 1 and row.last_error.startswith("Blocked")


# --- Signatures -----------------------------------------------------------------


def test_verify_signature() -> None:
    secret, body = "whsec_test", b'{"id":"evt_1","type":"clone.created"}'
    now = int(time.time())
    header = signature_header(secret, now, body)
    assert header == f"t={now},v1={sign(secret, now, body)}"
    assert verify_signature(secret, header, body)
    assert not verify_signature(secret, header, body + b" ")  # tampered body
    assert not verify_signature(secret, header, b'{"id":"evt_1","type":"clone.updated"}')
    assert not verify_signature("whsec_other", header, body)  # wrong secret
    old = signature_header(secret, now - 301, body)
    assert not verify_signature(secret, old, body)  # replay: older than 5 minutes
    assert verify_signature(secret, old, body, tolerance=600)
    assert not verify_signature(secret, signature_header(secret, now + 400, body), body)  # from the future
    for bad in (None, "", "v1=abc", f"t={now}", "t=abc,v1=00", f"t={now},v1="):
        assert not verify_signature(secret, bad, body)


# --- Delivery -------------------------------------------------------------------


def test_delivery_success_headers_and_envelope(owner: TestClient, db_session: Session) -> None:
    hook = make_hook(owner)
    owner_id = user_id(db_session, USER["email"])
    emit("clone.created", {"clone_id": "abc", "status": "draft"}, user_id=owner_id)
    row = deliveries(db_session)[0]
    assert row.status == "pending" and row.event_id.startswith("evt_") and row.attempts == 0

    receiver = Receiver(204)
    assert delivery_module.process_due(transport=receiver.transport) == 1
    request = receiver.requests[0]
    assert request.method == "POST"
    assert request.url.host == PUBLIC_IP and request.headers["host"] == "hooks.example.com"  # pinned address
    assert request.extensions.get("sni_hostname") == "hooks.example.com"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["user-agent"] == "AHC-Webhooks/1.0"
    assert request.headers["x-ahc-event-id"] == row.event_id
    assert request.headers["x-ahc-event-type"] == "clone.created"
    assert verify_signature(hook["secret"], request.headers["x-ahc-signature"], request.content)
    body = json.loads(request.content)
    assert set(body) == {"id", "type", "timestamp", "data"}
    assert body["id"] == row.event_id and body["type"] == "clone.created"
    assert body["data"] == {"clone_id": "abc", "status": "draft"}
    assert body["timestamp"].endswith("Z") and datetime.fromisoformat(body["timestamp"].replace("Z", "+00:00"))

    row = deliveries(db_session)[0]
    assert row.status == "delivered" and row.attempts == 1 and row.response_status == 204
    assert row.delivered_at is not None and row.last_error is None
    endpoint = db_session.get(WebhookEndpoint, row.webhook_id)
    assert endpoint.last_delivery_at is not None and endpoint.failure_count == 0


def test_only_matching_active_endpoints_get_events(owner: TestClient, sara: TestClient, db_session: Session) -> None:
    clone_hook = make_hook(owner, events=("clone.created",))
    make_hook(owner, events=("voice.completed",))
    off = make_hook(owner, events=("clone.created",), is_active=False)
    make_hook(sara, events=("clone.created",))
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    rows = deliveries(db_session)
    assert [str(r.webhook_id) for r in rows] == [clone_hook["id"]]
    assert off["id"] not in {str(r.webhook_id) for r in rows}
    emit("clone.deleted", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))  # unknown: ignored
    assert len(deliveries(db_session)) == 1


def test_emit_does_nothing_when_disabled(owner: TestClient, db_session: Session, monkeypatch) -> None:
    make_hook(owner)
    monkeypatch.setattr(get_settings(), "webhook_delivery_enabled", False)
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    assert deliveries(db_session) == []


def test_payload_data_drops_text_and_secrets(owner: TestClient, db_session: Session) -> None:
    make_hook(owner)
    emit(
        "clone.created",
        {"clone_id": "c1", "content": "hello", "message_text": "secret plan", "api_key": "x", "nested": {"a": 1}},
        user_id=user_id(db_session, USER["email"]),
    )
    assert deliveries(db_session)[0].payload["data"] == {"clone_id": "c1"}


def test_retry_with_backoff_after_500_and_timeout(owner: TestClient, db_session: Session) -> None:
    make_hook(owner)
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    receiver = Receiver(500, httpx.ReadTimeout("slow"), 200)
    start = datetime.now(UTC)

    delivery_module.process_due(now=start, transport=receiver.transport)
    row = deliveries(db_session)[0]
    assert row.status == "pending" and row.attempts == 1 and row.response_status == 500
    assert row.last_error == "HTTP 500"
    assert abs((aware(row.next_retry_at) - start).total_seconds() - 30) < 2
    assert db_session.get(WebhookEndpoint, row.webhook_id).failure_count == 1

    # Not due yet: nothing is sent.
    assert delivery_module.process_due(now=start + timedelta(seconds=10), transport=receiver.transport) == 0
    assert len(receiver.requests) == 1

    second = start + timedelta(seconds=31)
    delivery_module.process_due(now=second, transport=receiver.transport)
    row = deliveries(db_session)[0]
    assert row.status == "pending" and row.attempts == 2 and row.response_status is None
    assert row.last_error.startswith("Timed out")
    assert abs((aware(row.next_retry_at) - second).total_seconds() - 60) < 2

    delivery_module.process_due(now=second + timedelta(seconds=61), transport=receiver.transport)
    row = deliveries(db_session)[0]
    assert row.status == "delivered" and row.attempts == 3
    assert db_session.get(WebhookEndpoint, row.webhook_id).failure_count == 0
    # Every attempt carried the same event id (receivers dedupe on it).
    ids = {request.headers["x-ahc-event-id"] for request in receiver.requests}
    assert ids == {row.event_id} and len(receiver.requests) == 3
    assert {json.loads(request.content)["id"] for request in receiver.requests} == {row.event_id}


def test_backoff_schedule() -> None:
    assert [delivery_module.backoff_seconds(n) for n in range(1, 9)] == [30, 60, 120, 240, 480, 960, 1920, 3600]


def test_fails_after_max_retries_then_manual_retry(owner: TestClient, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_max_retries", 3)
    hook = make_hook(owner)
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    failing = Receiver(httpx.ConnectError("refused"))
    at = datetime.now(UTC)
    for _ in range(5):
        at += timedelta(hours=2)
        delivery_module.process_due(now=at, transport=failing.transport)
    row = deliveries(db_session)[0]
    assert row.status == "failed" and row.attempts == 3 and row.next_retry_at is None
    assert row.last_error == "Connection failed (ConnectError)"
    assert len(failing.requests) == 3
    assert db_session.get(WebhookEndpoint, row.webhook_id).failure_count == 3

    listed = owner.get(f"/api/developer/webhooks/{hook['id']}/deliveries").json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "failed"
    assert set(listed["items"][0]) == {
        "id", "event_id", "event_type", "status", "response_status", "attempts",
        "last_error", "delivered_at", "next_retry_at", "created_at",
    }

    retried = owner.post(f"/api/developer/webhooks/{hook['id']}/deliveries/{row.id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending" and retried.json()["event_id"] == row.event_id
    ok = Receiver(200)
    delivery_module.process_due(transport=ok.transport)
    row = deliveries(db_session)[0]
    assert row.status == "delivered" and ok.requests[0].headers["x-ahc-event-id"] == row.event_id
    # Only failed deliveries can be retried.
    assert owner.post(f"/api/developer/webhooks/{hook['id']}/deliveries/{row.id}/retry").status_code == 400
    missing = "00000000-0000-0000-0000-000000000000"
    assert owner.post(f"/api/developer/webhooks/{hook['id']}/deliveries/{missing}/retry").status_code == 404


def test_redirects_are_not_followed(owner: TestClient, db_session: Session) -> None:
    make_hook(owner)
    emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    receiver = Receiver(302)
    delivery_module.process_due(transport=receiver.transport)
    row = deliveries(db_session)[0]
    assert len(receiver.requests) == 1 and row.status == "pending" and row.response_status == 302
    assert "redirect" in row.last_error


def test_send_test_event(owner: TestClient, db_session: Session, monkeypatch) -> None:
    hook = make_hook(owner)
    receiver = Receiver(200)
    monkeypatch.setattr(delivery_module, "INLINE", True)
    monkeypatch.setattr(delivery_module, "TRANSPORT", receiver.transport)
    response = owner.post(f"/api/developer/webhooks/{hook['id']}/test")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "delivered"
    body = json.loads(receiver.requests[0].content)
    assert body["type"] == "webhook.test" and body["data"]["webhook_id"] == hook["id"]
    assert verify_signature(hook["secret"], receiver.requests[0].headers["x-ahc-signature"], receiver.requests[0].content)

    # Queued (not inline): pending until the worker runs.
    monkeypatch.setattr(delivery_module, "INLINE", False)
    queued = owner.post(f"/api/developer/webhooks/{hook['id']}/test").json()
    assert queued["status"] == "pending" and queued["delivery_id"]
    owner.patch(f"/api/developer/webhooks/{hook['id']}", json={"is_active": False})
    assert owner.post(f"/api/developer/webhooks/{hook['id']}/test").status_code == 400


def test_deliveries_pagination(owner: TestClient, db_session: Session) -> None:
    hook = make_hook(owner)
    owner_id = user_id(db_session, USER["email"])
    for n in range(5):
        emit("clone.created", {"clone_id": f"c{n}"}, user_id=owner_id)
    page = owner.get(f"/api/developer/webhooks/{hook['id']}/deliveries?page=2&limit=2").json()
    assert page["page"] == 2 and page["limit"] == 2 and page["total"] == 5 and len(page["items"]) == 2
    assert owner.get(f"/api/developer/webhooks/{hook['id']}/deliveries?limit=101").status_code in (400, 422)
    assert owner.get(f"/api/developer/webhooks/{hook['id']}/deliveries?page=0").status_code in (400, 422)


def test_emit_never_blocks(owner: TestClient, db_session: Session, monkeypatch) -> None:
    """The normal mode: emit only queues in memory; the worker writes and sends later."""
    make_hook(owner)
    monkeypatch.setattr(delivery_module, "SYNC_WRITE", False)

    def down(request):
        time.sleep(3)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(delivery_module, "TRANSPORT", httpx.MockTransport(down))
    started = time.monotonic()
    for _ in range(20):
        emit("clone.created", {"clone_id": "c1"}, user_id=user_id(db_session, USER["email"]))
    assert time.monotonic() - started < 0.5
    assert deliveries(db_session) == [] and delivery_module.pending_events() == 20
    assert delivery_module.drain_events() == 20
    assert len(deliveries(db_session, status="pending")) == 20


def test_worker_thread_starts_and_stops() -> None:
    delivery_module.start_worker()
    try:
        assert delivery_module.worker_running()
        delivery_module.start_worker()  # idempotent
    finally:
        delivery_module.stop_worker()
    assert not delivery_module.worker_running()


# --- Events from real flows -----------------------------------------------------


def test_clone_and_chat_flows_emit_events(owner: TestClient, db_session: Session) -> None:
    make_hook(
        owner, events=("clone.created", "clone.updated", "conversation.created", "message.completed")
    )
    clone = owner.post("/api/clones", json=CLONE)
    assert clone.status_code == 201, clone.text
    clone_id = clone.json()["id"]
    created = deliveries(db_session, event_type="clone.created")
    assert len(created) == 1 and created[0].payload["data"]["clone_id"] == clone_id

    assert owner.patch(f"/api/clones/{clone_id}", json={"bio": "New bio"}).status_code == 200
    updated = deliveries(db_session, event_type="clone.updated")
    assert len(updated) == 1 and updated[0].payload["data"]["changed_fields"] == ["bio"]
    assert "New bio" not in json.dumps(updated[0].payload)

    question = "What is my favourite secret recipe?"
    chat = owner.post(f"/api/clones/{clone_id}/chat", json={"message": question})
    assert chat.status_code == 200, chat.text
    answer = chat.json()["message"]["content"]
    conversation_id = chat.json()["conversation_id"]
    started = deliveries(db_session, event_type="conversation.created")
    assert len(started) == 1 and started[0].payload["data"]["conversation_id"] == conversation_id
    completed = deliveries(db_session, event_type="message.completed")
    assert len(completed) == 1
    data = completed[0].payload["data"]
    assert data["message_id"] == chat.json()["message"]["id"] and data["clone_id"] == clone_id
    assert data["streamed"] is False and data["role"] == "assistant"

    # A follow-up in the same conversation: a message, but no new conversation.
    again = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "And?", "conversation_id": conversation_id})
    assert again.status_code == 200
    assert len(deliveries(db_session, event_type="conversation.created")) == 1
    assert len(deliveries(db_session, event_type="message.completed")) == 2

    # Streaming path.
    with owner.stream("POST", f"/api/clones/{clone_id}/chat/stream", json={"message": question}) as response:
        assert response.status_code == 200
        "".join(response.iter_text())
    streamed = deliveries(db_session, event_type="message.completed")
    assert len(streamed) == 3 and streamed[-1].payload["data"]["streamed"] is True

    everything = json.dumps([row.payload for row in deliveries(db_session)])
    assert question not in everything and answer not in everything and "secret recipe" not in everything


def test_org_clone_events_reach_owner_and_organization(owner: TestClient, db_session: Session) -> None:
    from app.services.clone_service import _emit

    org = make_org(db_session, USER["email"])
    personal = make_hook(owner, events=("clone.updated",))
    org_hook = make_hook(owner, events=("clone.updated",), organization_id=str(org.id))
    clone_id = owner.post("/api/clones", json=CLONE).json()["id"]
    from app.models import CloneProfile

    clone = db_session.get(CloneProfile, __import__("uuid").UUID(clone_id))
    clone.organization_id = org.id
    db_session.commit()
    before = len(deliveries(db_session))
    _emit("clone.updated", clone, changed_fields=["organization_id"])
    rows = deliveries(db_session)[before:]
    assert {str(r.webhook_id) for r in rows} == {personal["id"], org_hook["id"]}
    assert len({r.event_id for r in rows}) == 1


def test_subscription_status_change_emits(owner: TestClient, db_session: Session) -> None:
    import uuid

    from app.billing.service import set_subscription_status
    from app.models import Subscription

    make_hook(owner, events=("subscription.updated",))
    sub = Subscription(user_id=user_id(db_session, USER["email"]), plan_id=uuid.uuid4(), status="active")
    db_session.add(sub)
    db_session.commit()
    set_subscription_status(db_session, sub, "cancelled")
    rows = deliveries(db_session, event_type="subscription.updated")
    assert len(rows) == 1
    assert rows[0].payload["data"]["status"] == "cancelled" and rows[0].payload["data"]["previous_status"] == "active"
    set_subscription_status(db_session, sub, "cancelled")  # no change: no event
    assert len(deliveries(db_session, event_type="subscription.updated")) == 1


def test_usage_limit_event_is_sent_once_per_window(owner: TestClient, db_session: Session) -> None:
    make_hook(owner, events=("usage.limit_reached",))
    owner_id = user_id(db_session, USER["email"])
    for _ in range(3):
        emit("usage.limit_reached", {"limit": "api_requests", "used": 10, "allowed": 10}, user_id=owner_id)
    assert len(deliveries(db_session, event_type="usage.limit_reached")) == 1


def test_public_and_voice_settings_send_clone_updated(owner: TestClient, db_session: Session) -> None:
    make_hook(owner, events=("clone.updated",))
    clone_id = owner.post("/api/clones", json=CLONE).json()["id"]
    before = len(deliveries(db_session, event_type="clone.updated"))
    assert owner.patch(f"/api/clones/{clone_id}/public-settings", json={"visibility": "public"}).status_code == 200
    assert owner.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
    ).status_code == 200
    rows = deliveries(db_session, event_type="clone.updated")
    assert len(rows) == before + 2
    fields = [set(row.payload["data"]["changed_fields"]) for row in rows[-2:]]
    assert "visibility" in fields[0] and "voice_enabled" in fields[1]


def test_endpoint_is_disabled_after_repeated_failures(owner: TestClient, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_auto_disable_after", 2)
    monkeypatch.setattr(get_settings(), "webhook_max_retries", 5)
    hook = make_hook(owner, events=("clone.created",))
    owner.post("/api/clones", json=CLONE)
    failing = httpx.MockTransport(lambda request: httpx.Response(500))
    later = datetime.now(UTC)
    for _ in range(3):
        later += timedelta(hours=2)
        delivery_module.process_due(now=later, transport=failing)
    endpoint = db_session.get(WebhookEndpoint, __import__("uuid").UUID(hook["id"]))
    db_session.refresh(endpoint)
    assert endpoint.is_active is False and endpoint.failure_count >= 2
