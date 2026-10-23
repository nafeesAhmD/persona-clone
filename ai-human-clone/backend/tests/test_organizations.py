"""Phase 13: organizations, members, invitations, roles, ownership and org clones."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember
from app.models.notification import Notification
from app.models.teams import OrganizationAuditLog, OrganizationInvitation
from app.org.services import rate_limit as org_rate_limit
from app.org.services.invitation import hash_token
from tests.conftest import USER

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
OMAR = {**USER, "email": "omar@example.com", "username": "omar", "full_name": "Omar"}
CLONE = {"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}


@pytest.fixture(autouse=True)
def _reset_org_limits():
    org_rate_limit.reset()
    yield
    org_rate_limit.reset()


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def signup(make_client, data: dict) -> TestClient:
    browser = make_client()
    response = browser.post("/api/auth/register", json=data)
    assert response.status_code == 201, response.text
    return browser


def me(browser: TestClient) -> dict:
    return browser.get("/api/auth/me").json()


def create_org(browser: TestClient, name: str = "Acme Team", **extra) -> dict:
    response = browser.post("/api/organizations", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def invite(browser: TestClient, org_id: str, email: str, role: str = "editor") -> dict:
    response = browser.post(f"/api/organizations/{org_id}/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


def join(owner: TestClient, member: TestClient, org_id: str, data: dict, role: str = "editor") -> dict:
    """Invite `data`'s e-mail and accept with that account. Returns the member row."""
    token = invite(owner, org_id, data["email"], role)["token"]
    response = member.post(f"/api/invitations/{token}/accept")
    assert response.status_code == 200, response.text
    members = owner.get(f"/api/organizations/{org_id}/members").json()
    return next(m for m in members if m["user_id"] == me(member)["id"])


def test_create_organization_makes_owner_an_active_member(owner: TestClient, db_session: Session) -> None:
    org = create_org(owner, "Acme Team", description="Our team")
    assert org["name"] == "Acme Team" and org["slug"] == "acme-team" and org["is_active"] is True
    assert org["owner_id"] == me(owner)["id"]
    row = db_session.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == uuid.UUID(org["id"])))
    assert row is not None and row.role == "owner" and row.status == "active"
    assert str(row.user_id) == org["owner_id"]
    assert db_session.scalar(select(OrganizationAuditLog.action)) == "organization_created"
    # Same name again gets a different slug.
    assert create_org(owner, "Acme Team")["slug"] != "acme-team"


def test_list_get_and_update_organization(owner: TestClient) -> None:
    first = create_org(owner, "Org A")
    second = create_org(owner, "Org B", slug="Org B Custom")
    assert second["slug"] == "org-b-custom"
    assert [o["name"] for o in owner.get("/api/organizations").json()] == ["Org A", "Org B"]
    assert owner.get(f"/api/organizations/{first['id']}").json()["name"] == "Org A"

    updated = owner.patch(f"/api/organizations/{first['id']}", json={"name": "Org A+", "description": "new"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Org A+" and updated.json()["description"] == "new"
    taken = owner.patch(f"/api/organizations/{first['id']}", json={"slug": second["slug"]})
    assert taken.status_code == 400

    assert owner.delete(f"/api/organizations/{second['id']}").status_code == 200
    assert [o["name"] for o in owner.get("/api/organizations").json()] == ["Org A+"]


def test_invitation_create_and_accept(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    created = invite(owner, org["id"], "Sara@Example.com", "editor")
    assert created["email"] == "sara@example.com" and created["role"] == "editor" and created["status"] == "pending"
    token = created["token"]
    row = db_session.get(OrganizationInvitation, uuid.UUID(created["id"]))
    assert row.token_hash == hash_token(token) and token not in row.token_hash
    listed = owner.get(f"/api/organizations/{org['id']}/invitations").json()
    assert len(listed) == 1 and "token" not in listed[0]
    # The invited user was told about it.
    notes = db_session.scalars(select(Notification).where(Notification.type == "invitation_received")).all()
    assert len(notes) == 1 and str(notes[0].user_id) == me(sara)["id"]
    # A second pending invite for the same address is refused.
    again = owner.post(f"/api/organizations/{org['id']}/invitations", json={"email": SARA["email"]})
    assert again.status_code == 400

    # Before accepting, Sara can't see the organization.
    assert sara.get(f"/api/organizations/{org['id']}").status_code == 403
    accepted = sara.post(f"/api/invitations/{token}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "editor"
    assert sara.get(f"/api/organizations/{org['id']}").status_code == 200
    assert [o["id"] for o in sara.get("/api/organizations").json()] == [org["id"]]
    roles = {m["user_id"]: m["role"] for m in owner.get(f"/api/organizations/{org['id']}/members").json()}
    assert roles == {me(owner)["id"]: "owner", me(sara)["id"]: "editor"}
    # A token works once.
    assert sara.post(f"/api/invitations/{token}/accept").status_code == 400
    assert db_session.get(OrganizationInvitation, row.id).status == "accepted"
    # Inviting an existing member is refused.
    assert owner.post(f"/api/organizations/{org['id']}/invitations", json={"email": SARA["email"]}).status_code == 400


def test_invitation_only_for_the_invited_email_and_not_expired(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    omar = signup(make_client, OMAR)
    sara = signup(make_client, SARA)
    token = invite(owner, org["id"], SARA["email"])["token"]
    assert omar.post(f"/api/invitations/{token}/accept").status_code == 403
    assert omar.get(f"/api/organizations/{org['id']}").status_code == 403
    assert omar.post("/api/invitations/not-a-real-token/accept").status_code == 400

    invitation = db_session.scalar(select(OrganizationInvitation))
    invitation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert sara.post(f"/api/invitations/{token}/accept").status_code == 400
    assert db_session.get(OrganizationInvitation, invitation.id).status == "expired"
    # Nobody can be invited as owner.
    as_owner = owner.post(f"/api/organizations/{org['id']}/invitations", json={"email": OMAR["email"], "role": "owner"})
    assert as_owner.status_code == 400


def test_decline_and_cancel_invitation(owner: TestClient, make_client) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    token = invite(owner, org["id"], SARA["email"])["token"]
    assert sara.post(f"/api/invitations/{token}/decline").status_code == 200
    assert sara.post(f"/api/invitations/{token}/accept").status_code == 400

    second = invite(owner, org["id"], SARA["email"])
    assert owner.delete(f"/api/organizations/{org['id']}/invitations/{second['id']}").status_code == 200
    assert sara.post(f"/api/invitations/{second['token']}/accept").status_code == 400


def test_viewer_and_editor_cannot_manage(owner: TestClient, make_client) -> None:
    org = create_org(owner)
    viewer = signup(make_client, SARA)
    editor = signup(make_client, OMAR)
    join(owner, viewer, org["id"], SARA, "viewer")
    editor_row = join(owner, editor, org["id"], OMAR, "editor")
    oid = org["id"]

    for browser in (viewer, editor):
        assert browser.post(f"/api/organizations/{oid}/invitations", json={"email": "x@example.com"}).status_code == 403
        assert browser.get(f"/api/organizations/{oid}/invitations").status_code == 403
        assert browser.patch(f"/api/organizations/{oid}", json={"name": "Hacked"}).status_code == 403
        assert browser.patch(f"/api/organizations/{oid}/members/{editor_row['id']}", json={"role": "admin"}).status_code == 403
        assert browser.delete(f"/api/organizations/{oid}/members/{editor_row['id']}").status_code == 403
        assert browser.delete(f"/api/organizations/{oid}").status_code == 403
        assert browser.get(f"/api/organizations/{oid}/analytics/overview").status_code == 403
        # ...but members can read the organization, its members and its usage.
        assert browser.get(f"/api/organizations/{oid}").status_code == 200
        assert len(browser.get(f"/api/organizations/{oid}/members").json()) == 3
        assert browser.get(f"/api/organizations/{oid}/usage").status_code == 200
    assert owner.get(f"/api/organizations/{oid}").json()["name"] == "Acme Team"


def test_role_changes(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    omar = signup(make_client, OMAR)
    sara_row = join(owner, sara, org["id"], SARA, "viewer")
    omar_row = join(owner, omar, org["id"], OMAR, "viewer")
    oid = org["id"]

    promoted = owner.patch(f"/api/organizations/{oid}/members/{sara_row['id']}", json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
    assert db_session.scalar(select(Notification).where(Notification.type == "role_changed")) is not None
    # An admin manages editors/viewers, but not admins, and nobody becomes owner this way.
    assert sara.patch(f"/api/organizations/{oid}/members/{omar_row['id']}", json={"role": "editor"}).status_code == 200
    assert sara.patch(f"/api/organizations/{oid}/members/{omar_row['id']}", json={"role": "admin"}).status_code == 403
    assert owner.patch(f"/api/organizations/{oid}/members/{omar_row['id']}", json={"role": "owner"}).status_code == 400
    owner_row = next(m for m in owner.get(f"/api/organizations/{oid}/members").json() if m["role"] == "owner")
    assert sara.patch(f"/api/organizations/{oid}/members/{owner_row['id']}", json={"role": "viewer"}).status_code == 400
    # Admins can invite.
    assert sara.post(f"/api/organizations/{oid}/invitations", json={"email": "new@example.com"}).status_code == 201


def test_remove_member(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    row = join(owner, sara, org["id"], SARA, "editor")
    removed = owner.delete(f"/api/organizations/{org['id']}/members/{row['id']}")
    assert removed.status_code == 200, removed.text
    note = db_session.scalar(select(Notification).where(Notification.type == "member_removed"))
    assert note is not None and SARA["email"] in note.message
    assert sara.get(f"/api/organizations/{org['id']}").status_code == 403
    assert sara.get("/api/organizations").json() == []
    owner_row = next(m for m in owner.get(f"/api/organizations/{org['id']}/members").json() if m["role"] == "owner")
    assert owner.delete(f"/api/organizations/{org['id']}/members/{owner_row['id']}").status_code == 400
    # A new invitation brings a removed member back.
    join(owner, sara, org["id"], SARA, "viewer")
    assert sara.get(f"/api/organizations/{org['id']}").status_code == 200


def test_leave_organization(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    join(owner, sara, org["id"], SARA, "viewer")
    assert owner.post(f"/api/organizations/{org['id']}/leave").status_code == 400  # owner must transfer first
    assert sara.post(f"/api/organizations/{org['id']}/leave").status_code == 200
    assert sara.get(f"/api/organizations/{org['id']}").status_code == 403
    assert db_session.scalar(select(Notification).where(Notification.type == "member_left")) is not None
    assert len([m for m in owner.get(f"/api/organizations/{org['id']}/members").json() if m["status"] == "active"]) == 1


def test_transfer_ownership(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    oid = org["id"]
    sara = signup(make_client, SARA)
    outsider = signup(make_client, OMAR)
    join(owner, sara, oid, SARA, "admin")
    sara_id, owner_id = me(sara)["id"], me(owner)["id"]

    assert sara.post(f"/api/organizations/{oid}/transfer-ownership", json={"target_user_id": sara_id}).status_code == 403
    not_member = owner.post(f"/api/organizations/{oid}/transfer-ownership", json={"target_user_id": me(outsider)["id"]})
    assert not_member.status_code == 400
    moved = owner.post(f"/api/organizations/{oid}/transfer-ownership", json={"target_user_id": sara_id})
    assert moved.status_code == 200, moved.text

    assert sara.get(f"/api/organizations/{oid}").json()["owner_id"] == sara_id
    roles = {m["user_id"]: m["role"] for m in sara.get(f"/api/organizations/{oid}/members").json()}
    assert roles == {owner_id: "admin", sara_id: "owner"}
    note = db_session.scalar(
        select(Notification).where(Notification.type == "ownership_transferred", Notification.user_id == uuid.UUID(sara_id))
    )
    assert note is not None and SARA["email"] in note.message
    # The old owner can leave now; the new one can't.
    assert sara.post(f"/api/organizations/{oid}/leave").status_code == 400
    assert owner.post(f"/api/organizations/{oid}/leave").status_code == 200


def test_assign_clone_and_editor_access(owner: TestClient, make_client, db_session: Session) -> None:
    org = create_org(owner)
    oid = org["id"]
    clone = owner.post("/api/clones", json=CLONE).json()
    editor = signup(make_client, SARA)
    viewer = signup(make_client, OMAR)
    join(owner, editor, oid, SARA, "editor")
    join(owner, viewer, oid, OMAR, "viewer")

    # Only the clone's owner (who manages the org) can assign it.
    assert editor.post(f"/api/organizations/{oid}/clones/{clone['id']}").status_code == 403
    assigned = owner.post(f"/api/organizations/{oid}/clones/{clone['id']}")
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["organization_id"] == oid
    assert [c["id"] for c in viewer.get(f"/api/organizations/{oid}/clones").json()] == [clone["id"]]

    base = f"/api/organizations/{oid}/clones/{clone['id']}"
    created = editor.post(f"{base}/memories", json={"memory_type": "fact", "content": "Ayaan maintains the billing service."})
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]
    assert created.json()["status"] == "approved"
    # The memory belongs to the clone (its owner sees it in their own view too).
    assert [m["id"] for m in owner.get(f"/api/clones/{clone['id']}/memories").json()] == [memory_id]
    assert [m["id"] for m in viewer.get(f"{base}/memories").json()] == [memory_id]
    edited = editor.patch(f"{base}/memories/{memory_id}", json={"content": "Ayaan maintains the payments service."})
    assert edited.status_code == 200 and "payments" in edited.json()["content"]
    # Viewers read only; approving is for admins/owners.
    assert viewer.post(f"{base}/memories", json={"memory_type": "fact", "content": "Nope"}).status_code == 403
    assert viewer.delete(f"{base}/memories/{memory_id}").status_code == 403
    assert editor.post(f"{base}/memories/{memory_id}/approve").status_code == 403
    assert owner.post(f"{base}/memories/{memory_id}/approve").status_code == 200

    doc = editor.post(f"{base}/knowledge", json={"title": "Stack", "content": "Ayaan works with FastAPI and Postgres."})
    assert doc.status_code == 201, doc.text
    assert len(viewer.get(f"{base}/documents").json()) == 1
    assert viewer.get(f"/api/organizations/{oid}/analytics/clone/{clone['id']}").status_code == 200
    usage = owner.get(f"/api/organizations/{oid}/usage").json()
    assert usage["clones"]["used"] == 1 and usage["members"]["used"] == 3 and usage["documents"]["used"] == 1
    assert owner.get(f"/api/organizations/{oid}/analytics/overview").json()["clones"] == 1

    assert editor.delete(f"{base}/memories/{memory_id}").status_code == 204
    # Unassigning ends the members' access.
    assert owner.delete(f"/api/organizations/{oid}/clones/{clone['id']}").status_code == 200
    assert editor.get(f"{base}/memories").status_code == 403
    assert owner.get(f"/api/organizations/{oid}/clones").json() == []


def test_cross_organization_isolation(owner: TestClient, make_client) -> None:
    org = create_org(owner)
    oid = org["id"]
    clone = owner.post("/api/clones", json=CLONE).json()
    assert owner.post(f"/api/organizations/{oid}/clones/{clone['id']}").status_code == 200

    stranger = signup(make_client, SARA)
    other = create_org(stranger, "Other Org")
    base = f"/api/organizations/{oid}/clones/{clone['id']}"
    for path in (
        f"/api/organizations/{oid}",
        f"/api/organizations/{oid}/members",
        f"/api/organizations/{oid}/usage",
        f"/api/organizations/{oid}/subscription",
        f"/api/organizations/{oid}/features",
        f"/api/organizations/{oid}/clones",
        f"/api/organizations/{oid}/notifications",
        f"/api/organizations/{oid}/analytics/clone/{clone['id']}",
        f"{base}/memories",
        f"{base}/documents",
    ):
        assert stranger.get(path).status_code in (403, 404), path
    assert stranger.post(f"{base}/memories", json={"memory_type": "fact", "content": "x"}).status_code == 403
    assert stranger.patch(f"/api/organizations/{oid}", json={"name": "Mine"}).status_code == 403
    assert stranger.post(f"/api/organizations/{oid}/invitations", json={"email": "a@example.com"}).status_code == 403
    # A clone of one org can't be reached through another org's routes, nor assigned twice.
    assert stranger.get(f"/api/organizations/{other['id']}/clones/{clone['id']}/memories").status_code == 403
    assert owner.post(f"/api/organizations/{other['id']}/clones/{clone['id']}").status_code == 403
    assert [o["id"] for o in stranger.get("/api/organizations").json()] == [other["id"]]


def test_notifications_listing(owner: TestClient, make_client) -> None:
    org = create_org(owner)
    sara = signup(make_client, SARA)
    join(owner, sara, org["id"], SARA, "viewer")
    notes = owner.get(f"/api/organizations/{org['id']}/notifications").json()
    assert [n["type"] for n in notes] == ["invitation_accepted"] and notes[0]["is_read"] is False
    assert owner.patch(f"/api/organizations/{org['id']}/notifications/{notes[0]['id']}/read").status_code == 200
    assert owner.get(f"/api/organizations/{org['id']}/notifications?unread_only=true").json() == []
    assert owner.delete(f"/api/organizations/{org['id']}/notifications/{notes[0]['id']}").status_code == 200
    assert owner.get(f"/api/organizations/{org['id']}/notifications").json() == []


def test_org_creation_is_rate_limited(owner: TestClient, db_session: Session) -> None:
    # The decorator wraps a plain (sync) route: it must run it, then refuse past the limit.
    for i in range(5):
        create_org(owner, f"Org {i}")
    refused = owner.post("/api/organizations", json={"name": "One too many"})
    assert refused.status_code == 429
    assert "Too many requests" in refused.json()["detail"]
    assert int(refused.headers["Retry-After"]) > 0
    assert len(db_session.scalars(select(Organization)).all()) == 5


def test_member_list_says_who_each_member_is(owner: TestClient, make_client) -> None:
    """Phase 15: member cards show the member's e-mail and name, not just an id."""
    org = create_org(owner)
    sara = signup(make_client, SARA)
    join(owner, sara, org["id"], SARA, "viewer")
    members = {m["email"]: m for m in sara.get(f"/api/organizations/{org['id']}/members").json()}
    assert set(members) == {"ayaan@example.com", "sara@example.com"}
    assert members["sara@example.com"]["full_name"] == "Sara" and members["sara@example.com"]["role"] == "viewer"
    assert members["ayaan@example.com"]["role"] == "owner"
    assert all("hashed_password" not in m and "password" not in m for m in members.values())
