"""Phase 14: the developer dashboard (/api/developer/overview, /usage) and the admin
developer view (/api/admin/developer/*)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, ApiKey, Organization, OrganizationMember, User
from tests.conftest import USER, make_admin

ADMIN = {"email": "admin@example.com", "username": "admin", "full_name": "Admin", "password": "AdminPassword123!"}
MISSING_CLONE = "/api/v1/clones/00000000-0000-0000-0000-000000000000"  # authenticated, then 404
SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}


def make_key(client: TestClient, name: str = "Website bot", scopes=("clone:read",), **extra) -> dict:
    response = client.post("/api/developer/keys", json={"name": name, "scopes": list(scopes), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def call(client: TestClient, key: str, path: str = "/api/v1/me"):
    return client.get(path, headers={"Authorization": f"Bearer {key}"})


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def sara(make_client) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=SARA).status_code == 201
    return browser


@pytest.fixture
def admin(make_client, db_session: Session) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=ADMIN).status_code == 201
    make_admin(db_session, ADMIN["email"])
    return browser


def _assert_no_secrets(body, *secrets: str) -> None:
    text = str(body)
    assert "key_hash" not in text and "secret" not in text.lower()
    for secret in secrets:
        assert secret not in text


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


def test_dashboard_requires_login(make_client) -> None:
    anonymous = make_client()
    for path in ("/api/developer/overview", "/api/developer/usage"):
        assert anonymous.get(path).status_code == 401


def test_overview_counts_requests(owner: TestClient, make_client) -> None:
    empty = owner.get("/api/developer/overview")
    assert empty.status_code == 200, empty.text
    assert empty.json()["api_requests_30d"] == 0 and empty.json()["active_keys"] == 0

    first = make_key(owner)
    second = make_key(owner, name="Mobile app")
    revoked = make_key(owner, name="Old")
    assert owner.post(f"/api/developer/keys/{revoked['id']}/revoke").status_code == 200
    outsider = make_client()
    for _ in range(3):
        assert call(outsider, first["key"]).status_code == 200
    assert call(outsider, second["key"]).status_code == 200
    # An authenticated call that fails (unknown clone).
    assert call(outsider, second["key"], MISSING_CLONE).status_code >= 400

    data = owner.get("/api/developer/overview").json()
    assert data["api_requests_30d"] == 5
    assert data["successful_requests_30d"] == 4 and data["failed_requests_30d"] == 1
    assert data["monthly_requests"] == 5
    assert data["active_keys"] == 2 and data["active_webhooks"] == 0
    assert data["plan"] == "free" and data["rate_limit_per_minute"] == 60
    assert data["chat_requests_30d"] == 0
    _assert_no_secrets(data, first["key"], second["key"])


def test_usage_breakdown(owner: TestClient, make_client) -> None:
    first = make_key(owner)
    second = make_key(owner, name="Mobile app")
    outsider = make_client()
    for _ in range(2):
        call(outsider, first["key"])
    call(outsider, second["key"])
    call(outsider, second["key"], MISSING_CLONE)

    response = owner.get("/api/developer/usage", params={"days": 7})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["days"] == 7 and len(data["per_day"]) == 7
    assert sum(d["requests"] for d in data["per_day"]) == 4
    assert sum(d["errors"] for d in data["per_day"]) == 1
    endpoints = {row["endpoint"]: row for row in data["by_endpoint"]}
    assert endpoints["GET /api/v1/me"]["requests"] == 3 and endpoints["GET /api/v1/me"]["errors"] == 0
    assert "GET /api/v1/clones/{id}" in endpoints
    keys = {row["name"]: row for row in data["by_key"]}
    assert keys["Website bot"]["requests"] == 2 and keys["Mobile app"]["requests"] == 2
    assert keys["Website bot"]["key_prefix"] == first["key_prefix"]
    _assert_no_secrets(data, first["key"], second["key"])

    assert owner.get("/api/developer/usage", params={"days": 0}).status_code == 400
    assert owner.get("/api/developer/usage", params={"days": 91}).status_code == 400


def test_usage_is_per_owner(owner: TestClient, sara: TestClient, make_client) -> None:
    key = make_key(owner)["key"]
    call(make_client(), key)
    assert sara.get("/api/developer/overview").json()["api_requests_30d"] == 0
    assert sara.get("/api/developer/usage").json()["by_key"] == []
    assert owner.get("/api/developer/overview").json()["api_requests_30d"] == 1


def test_organization_usage(owner: TestClient, sara: TestClient, make_client, db_session: Session) -> None:
    org = _org(db_session, USER["email"], SARA["email"], role="viewer")
    org_key = make_key(owner, organization_id=str(org.id))["key"]
    personal = make_key(owner, name="Personal")["key"]
    outsider = make_client()
    call(outsider, org_key)
    call(outsider, org_key)
    call(outsider, personal)

    params = {"organization_id": str(org.id)}
    org_view = owner.get("/api/developer/overview", params=params).json()
    assert org_view["api_requests_30d"] == 2 and org_view["active_keys"] == 1
    assert owner.get("/api/developer/overview").json()["api_requests_30d"] == 1
    assert [row["requests"] for row in owner.get("/api/developer/usage", params=params).json()["by_key"]] == [2]
    # A viewer of the organization can't see its developer usage.
    assert sara.get("/api/developer/overview", params=params).status_code == 403
    assert sara.get("/api/developer/usage", params=params).status_code == 403


def test_admin_endpoints_need_admin(owner: TestClient, make_client) -> None:
    paths = ("/api/admin/developer/overview", "/api/admin/developer/keys")
    for path in paths:
        assert make_client().get(path).status_code == 401
        assert owner.get(path).status_code == 403
    key = make_key(owner)
    assert owner.post(f"/api/admin/developer/keys/{key['id']}/revoke", json={}).status_code == 403


def test_admin_overview_and_keys(owner: TestClient, admin: TestClient, make_client, db_session: Session) -> None:
    org = _org(db_session, USER["email"])
    personal = make_key(owner)
    org_key = make_key(owner, name="Org key", organization_id=str(org.id))
    old = make_key(owner, name="Old")
    owner.post(f"/api/developer/keys/{old['id']}/revoke")
    outsider = make_client()
    call(outsider, personal["key"])
    call(outsider, org_key["key"])
    call(outsider, org_key["key"], MISSING_CLONE)

    response = admin.get("/api/admin/developer/overview")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["api_requests_24h"] == 3 and data["api_requests_30d"] == 3
    assert data["active_keys"] == 2 and data["revoked_keys"] == 1 and data["expired_keys"] == 0
    assert data["api_errors_24h"] == 1 and data["rate_limit_events_24h"] == 0
    assert data["webhook_failures_24h"] == 0
    assert data["usage_by_organization"] == [{"organization_id": str(org.id), "name": "Acme", "requests": 2}]
    assert data["usage_by_plan"] == [{"plan": "free", "requests": 3}]
    assert data["top_endpoints"][0]["endpoint"] == "GET /api/v1/me"

    listed = admin.get("/api/admin/developer/keys").json()
    assert listed["total"] == 3
    rows = {row["name"]: row for row in listed["items"]}
    assert rows["Website bot"]["owner"] == USER["email"].lower() and rows["Org key"]["owner"] == "Acme"
    assert rows["Old"]["status"] == "revoked"
    _assert_no_secrets(listed, personal["key"], org_key["key"], old["key"])
    hashes = list(db_session.scalars(select(ApiKey.key_hash)))
    assert not any(h in str(listed) for h in hashes)

    assert admin.get("/api/admin/developer/keys", params={"status": "revoked"}).json()["total"] == 1
    assert admin.get("/api/admin/developer/keys", params={"search": "acme"}).json()["total"] == 1
    assert admin.get("/api/admin/developer/keys", params={"search": "ayaan"}).json()["total"] == 2
    assert admin.get("/api/admin/developer/keys", params={"status": "bogus"}).status_code == 400


def test_admin_revoke_writes_audit(owner: TestClient, admin: TestClient, make_client, db_session: Session) -> None:
    key = make_key(owner)
    assert call(make_client(), key["key"]).status_code == 200

    response = admin.post(f"/api/admin/developer/keys/{key['id']}/revoke", json={"reason": "Leaked on GitHub"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "revoked"
    _assert_no_secrets(response.json(), key["key"])
    assert call(make_client(), key["key"]).status_code == 401

    db_session.expire_all()
    audits = list(db_session.scalars(select(AdminAuditLog).where(AdminAuditLog.action == "API_KEY_REVOKED")))
    assert len(audits) == 1
    assert audits[0].target_type == "api_key" and audits[0].target_id == key["id"]
    assert audits[0].details["reason"] == "Leaked on GitHub" and audits[0].details["prefix"] == key["key_prefix"]
    assert key["key"] not in str(audits[0].details)

    # Revoking again is a no-op (no second audit entry); unknown keys are 404.
    assert admin.post(f"/api/admin/developer/keys/{key['id']}/revoke").status_code == 200
    db_session.expire_all()
    assert len(list(db_session.scalars(select(AdminAuditLog).where(AdminAuditLog.action == "API_KEY_REVOKED")))) == 1
    missing = admin.post("/api/admin/developer/keys/00000000-0000-0000-0000-000000000000/revoke")
    assert missing.status_code == 404
