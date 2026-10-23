"""Phase 14 foundation: API keys, API-key auth, scopes, rate limits, request ids, CORS."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.developer.secrets import hash_api_key
from app.models import ApiKey, Organization, OrganizationMember, UsageEvent, User
from tests.conftest import USER

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}


def make_key(client: TestClient, scopes=("clone:read",), **extra) -> dict:
    response = client.post("/api/developer/keys", json={"name": "Website bot", "scopes": list(scopes), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def api(client: TestClient, key: str, path: str = "/api/v1/me", method: str = "GET", **kwargs):
    return client.request(method, path, headers={"Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}, **kwargs)


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def test_key_is_shown_once_and_stored_hashed(owner: TestClient, db_session: Session) -> None:
    created = make_key(owner, scopes=("clone:read", "clone:chat"))
    secret = created["key"]
    assert secret.startswith("ahc_live_") and len(secret) > 40
    assert created["key_prefix"] == secret[:17] and created["status"] == "active"
    row = db_session.scalar(select(ApiKey))
    assert row.key_hash == hash_api_key(secret) and secret not in (row.key_hash, row.key_prefix)
    listed = owner.get("/api/developer/keys").json()
    assert len(listed) == 1 and "key" not in listed[0] and secret not in str(listed)
    assert "key" not in owner.get(f"/api/developer/keys/{created['id']}").json()


def test_scopes_must_be_explicit_and_known(owner: TestClient) -> None:
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": []}).status_code == 400
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": ["everything"]}).status_code == 400
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": ["clone:read"], "is_admin": True}).status_code == 400
    scopes = owner.get("/api/developer/keys/scopes").json()
    assert {"clone:read", "clone:chat", "analytics:read"} <= {s["scope"] for s in scopes}


def test_expiry_rules(owner: TestClient) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    too_far = (datetime.now(UTC) + timedelta(days=get_settings().api_max_key_expiry_days + 5)).isoformat()
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": ["clone:read"], "expires_at": past}).status_code == 400
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": ["clone:read"], "expires_at": too_far}).status_code == 400


def test_api_key_authentication(owner: TestClient, make_client) -> None:
    key = make_key(owner)["key"]
    outsider = make_client()  # no cookies: API keys work without a browser session
    me = api(outsider, key)
    assert me.status_code == 200, me.text
    assert me.json() == {"name": "Website bot", "owner_type": "user", "scopes": ["clone:read"], "rate_limit_per_minute": 60}
    assert me.headers["x-request-id"].startswith("req_")
    assert me.headers["x-ratelimit-limit"] == "60"


@pytest.mark.parametrize(
    "header",
    [None, "Bearer nope", "Bearer ahc_live_" + "x" * 43, "Basic abc", "ahc_live_" + "x" * 43],
)
def test_invalid_credentials(make_client, header) -> None:
    headers = {"Authorization": header} if header else {}
    response = make_client().get("/api/v1/me", headers=headers)
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "authentication_failed" and body["request_id"].startswith("req_")
    assert set(body) == {"error", "message", "request_id"}


def test_session_cookie_is_not_an_api_key(owner: TestClient) -> None:
    # A logged-in browser can't call /api/v1 without a key: the two auth systems are separate.
    assert owner.get("/api/v1/me").status_code == 401


def test_revoked_and_expired_keys(owner: TestClient, make_client, db_session: Session) -> None:
    created = make_key(owner)
    other = make_client()
    assert owner.post(f"/api/developer/keys/{created['id']}/revoke").json()["status"] == "revoked"
    revoked = api(other, created["key"])
    assert revoked.status_code == 401 and "revoked" in revoked.json()["message"]
    assert owner.post(f"/api/developer/keys/{created['id']}/rotate").status_code == 400

    second = make_key(owner)
    row = db_session.get(ApiKey, __import__("uuid").UUID(second["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    expired = api(other, second["key"])
    assert expired.status_code == 401 and "expired" in expired.json()["message"]


def test_rotation_replaces_the_secret(owner: TestClient, make_client) -> None:
    created = make_key(owner)
    rotated = owner.post(f"/api/developer/keys/{created['id']}/rotate").json()
    assert rotated["id"] == created["id"] and rotated["key"] != created["key"]
    other = make_client()
    assert api(other, created["key"]).status_code == 401
    assert api(other, rotated["key"]).status_code == 200


def test_update_and_delete(owner: TestClient, make_client) -> None:
    created = make_key(owner)
    updated = owner.patch(f"/api/developer/keys/{created['id']}", json={"name": "Renamed", "scopes": ["clone:chat"]}).json()
    assert updated["name"] == "Renamed" and updated["scopes"] == ["clone:chat"]
    assert owner.delete(f"/api/developer/keys/{created['id']}").status_code == 204
    assert api(make_client(), created["key"]).status_code == 401


def test_disabled_account_key_is_rejected(owner: TestClient, make_client, db_session: Session) -> None:
    key = make_key(owner)["key"]
    user = db_session.scalar(select(User))
    user.is_active = False
    db_session.commit()
    response = api(make_client(), key)
    assert response.status_code == 403 and response.json()["error"] == "permission_denied"


def test_users_cannot_manage_each_others_keys(owner: TestClient, make_client) -> None:
    created = make_key(owner)
    sara = make_client()
    assert sara.post("/api/auth/register", json=SARA).status_code == 201
    assert sara.get("/api/developer/keys").json() == []
    for method, path in (
        ("GET", f"/api/developer/keys/{created['id']}"),
        ("POST", f"/api/developer/keys/{created['id']}/revoke"),
        ("POST", f"/api/developer/keys/{created['id']}/rotate"),
        ("DELETE", f"/api/developer/keys/{created['id']}"),
    ):
        assert sara.request(method, path).status_code == 404


def test_rate_limit_per_minute(owner: TestClient, make_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "api_rate_limit_per_minute", 3)
    monkeypatch.setattr(get_settings(), "api_rate_limit_burst", 50)
    key = make_key(owner)["key"]
    other = make_client()
    codes = [api(other, key).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    limited = api(other, key)
    body = limited.json()
    assert body["error"] == "rate_limit_exceeded" and body["retry_after"] >= 1
    assert int(limited.headers["retry-after"]) >= 1 and limited.headers["x-ratelimit-remaining"] == "0"


def test_burst_limit(owner: TestClient, make_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "api_rate_limit_burst", 2)
    key = make_key(owner)["key"]
    other = make_client()
    assert [api(other, key).status_code for _ in range(3)] == [200, 200, 429]


def test_monthly_api_request_limit(owner: TestClient, make_client, monkeypatch) -> None:
    from app.developer import limits

    monkeypatch.setitem(limits._DEFAULTS["free"], "api_requests", 2)
    key = make_key(owner)["key"]
    other = make_client()
    codes = [api(other, key).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert api(other, key).json()["error"] == "usage_limit_reached"


def test_usage_is_recorded_without_secrets(owner: TestClient, make_client, db_session: Session) -> None:
    created = make_key(owner)
    other = make_client()
    api(other, created["key"])
    other.get("/api/v1/me", headers={"Authorization": "Bearer ahc_live_" + "y" * 43})
    db_session.expire_all()
    events = list(db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "API_REQUEST")))
    assert len(events) == 1
    event = events[0]
    assert str(event.api_key_id) == created["id"] and event.endpoint == "GET /api/v1/me" and event.status_code == 200
    everything = str([(e.endpoint, e.provider, e.status) for e in db_session.scalars(select(UsageEvent))])
    assert created["key"] not in everything


def test_request_id_header_everywhere(client: TestClient) -> None:
    assert client.get("/api/health").headers["x-request-id"].startswith("req_")
    kept = client.get("/api/health", headers={"X-Request-ID": "trace-12345678"})
    assert kept.headers["x-request-id"] == "trace-12345678"
    unsafe = client.get("/api/health", headers={"X-Request-ID": "<script>"})
    assert unsafe.headers["x-request-id"].startswith("req_")


def test_internal_api_errors_keep_their_format(client: TestClient) -> None:
    assert client.get("/api/auth/me").json() == {"detail": "Not authenticated"}


def test_developer_api_cors(owner: TestClient, make_client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "api_allowed_origins", ["https://partner.example"])
    key = make_key(owner)["key"]
    browser = make_client()
    preflight = browser.options(
        "/api/v1/me", headers={"Origin": "https://partner.example", "Access-Control-Request-Method": "GET"}
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "https://partner.example"
    assert "access-control-allow-credentials" not in preflight.headers
    blocked = browser.options("/api/v1/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert blocked.status_code == 403
    ok = api(browser, key, headers={"Origin": "https://partner.example"})
    assert ok.headers["access-control-allow-origin"] == "https://partner.example"
    assert "access-control-allow-credentials" not in ok.headers
    evil = api(browser, key, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    # The app's own frontend CORS (with credentials) is unchanged.
    frontend = browser.get("/api/health", headers={"Origin": "http://localhost:3007"})
    assert frontend.headers["access-control-allow-credentials"] == "true"


def test_developer_openapi(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    assert schema["components"]["securitySchemes"]["ApiKeyAuth"]["scheme"] == "bearer"
    assert all(path.startswith("/api/v1") for path in schema["paths"])
    assert "/api/v1/me" in schema["paths"]
    assert client.get("/api/v1/docs").status_code == 200


def _org(db: Session, owner_email: str, member_email: str | None = None, role: str = "viewer") -> Organization:
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


def test_organization_keys(owner: TestClient, make_client, db_session: Session) -> None:
    sara = make_client()
    sara.post("/api/auth/register", json=SARA)
    org = _org(db_session, USER["email"], SARA["email"], role="viewer")
    created = make_key(owner, organization_id=str(org.id))
    assert created["owner_type"] == "organization"
    assert api(make_client(), created["key"]).json()["owner_type"] == "organization"
    # A viewer can neither create nor see organization keys.
    assert sara.post(
        "/api/developer/keys", json={"name": "x", "scopes": ["clone:read"], "organization_id": str(org.id)}
    ).status_code == 403
    assert sara.get("/api/developer/keys").json() == []
    # Deactivating the organization stops its keys.
    org.is_active = False
    db_session.commit()
    assert api(make_client(), created["key"]).status_code == 403


def test_unknown_developer_paths_use_the_error_format(client: TestClient) -> None:
    body = client.get("/api/v1/does-not-exist").json()
    assert body["error"] == "resource_not_found" and body["request_id"].startswith("req_")
    assert client.get("/api/nothing-here").json() == {"detail": "Not Found"}
