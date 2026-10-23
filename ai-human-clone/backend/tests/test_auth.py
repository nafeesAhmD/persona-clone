from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User
from tests.conftest import USER, open_to_public

COOKIE = get_settings().auth_cookie_name
LOGIN = {"email": USER["email"], "password": USER["password"]}


def test_register_returns_safe_user_and_starts_session(client: TestClient, db_session: Session):
    response = client.post("/api/auth/register", json=USER)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ayaan@example.com"  # normalised to lower case
    assert body["username"] == "ayaan"
    assert body["is_active"] is True
    assert "password" not in body and "hashed_password" not in body

    cookie_header = response.headers["set-cookie"]
    assert COOKIE in cookie_header and "HttpOnly" in cookie_header and "samesite=lax" in cookie_header.lower()

    stored = db_session.scalar(select(User).where(User.username == "ayaan"))
    assert stored.hashed_password != USER["password"]
    assert stored.hashed_password.startswith("$argon2id$")


def test_duplicate_email_rejected(client: TestClient, registered: dict):
    response = client.post("/api/auth/register", json={**USER, "username": "someone_else"})
    assert response.status_code == 409
    assert "email" in response.json()["detail"].lower()


def test_duplicate_username_rejected(client: TestClient, registered: dict):
    response = client.post("/api/auth/register", json={**USER, "email": "other@example.com", "username": "AYAAN"})
    assert response.status_code == 409
    assert "username" in response.json()["detail"].lower()


def test_weak_password_and_bad_email_rejected_with_400(client: TestClient):
    weak = client.post("/api/auth/register", json={**USER, "password": "short"})
    assert weak.status_code == 400
    assert "short" not in weak.text  # submitted values are not echoed back

    bad_email = client.post("/api/auth/register", json={**USER, "email": "not-an-email"})
    assert bad_email.status_code == 400


def test_login_succeeds_with_correct_password(make_client, registered: dict):
    browser = make_client()
    response = browser.post("/api/auth/login", json=LOGIN)
    assert response.status_code == 200
    assert response.json()["username"] == "ayaan"
    assert COOKIE in browser.cookies


def test_login_rejects_wrong_password_and_unknown_email_the_same_way(make_client, registered: dict):
    browser = make_client()
    wrong = browser.post("/api/auth/login", json={**LOGIN, "password": "WrongPassword999"})
    unknown = browser.post("/api/auth/login", json={**LOGIN, "email": "nobody@example.com"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}
    assert COOKIE not in browser.cookies


def test_me_requires_authentication(make_client):
    response = make_client().get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_tampered_token(make_client, registered: dict):
    browser = make_client()
    browser.cookies.set(COOKIE, "not.a.valid.token")
    assert browser.get("/api/auth/me").status_code == 401


def test_me_works_when_authenticated(client: TestClient, registered: dict):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == registered["id"]
    assert set(body) == {"id", "email", "username", "full_name", "is_active", "is_admin", "created_at"}


def test_inactive_user_gets_403(client: TestClient, registered: dict, db_session: Session):
    user = db_session.scalar(select(User).where(User.username == "ayaan"))
    user.is_active = False
    db_session.commit()

    assert client.get("/api/auth/me").status_code == 403
    assert client.post("/api/auth/login", json=LOGIN).status_code == 403


def test_logout_clears_the_session(client: TestClient, registered: dict):
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert COOKIE not in client.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_profile_update_works(client: TestClient, registered: dict):
    response = client.patch("/api/users/me", json={"full_name": "Ayaan Khan", "username": "ayaan_k"})
    assert response.status_code == 200
    assert response.json()["full_name"] == "Ayaan Khan"
    assert response.json()["username"] == "ayaan_k"
    assert client.get("/api/auth/me").json()["username"] == "ayaan_k"


def test_profile_update_rejects_taken_username_and_protected_fields(make_client, client: TestClient, registered: dict):
    other = make_client()
    other.post("/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara"})

    assert client.patch("/api/users/me", json={"username": "sara"}).status_code == 409
    assert client.patch("/api/users/me", json={"is_active": False}).status_code == 400
    assert client.patch("/api/users/me", json={"hashed_password": "x"}).status_code == 400
    assert client.patch("/api/users/me", json={"id": registered["id"]}).status_code == 400


def test_profile_update_requires_authentication(make_client):
    assert make_client().patch("/api/users/me", json={"full_name": "X"}).status_code == 401


def test_change_password_flow(make_client, client: TestClient, registered: dict):
    new_password = "NewPassword456!"

    wrong_current = client.post(
        "/api/auth/change-password", json={"current_password": "Nope12345", "new_password": new_password}
    )
    assert wrong_current.status_code == 400

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": USER["password"], "new_password": new_password},
    )
    assert changed.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # current session continues

    old = make_client().post("/api/auth/login", json=LOGIN)
    assert old.status_code == 401

    new = make_client().post("/api/auth/login", json={**LOGIN, "password": new_password})
    assert new.status_code == 200


def test_change_password_validates_new_password(client: TestClient, registered: dict):
    response = client.post(
        "/api/auth/change-password", json={"current_password": USER["password"], "new_password": "weak"}
    )
    assert response.status_code == 400


def test_clone_creation_requires_login_and_uses_the_owner(make_client, client: TestClient, registered: dict):
    clone = {"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}

    assert make_client().post("/api/clones", json=clone).status_code == 401

    created = client.post("/api/clones", json=clone)
    assert created.status_code == 201
    mine = client.get("/api/clones").json()
    assert [c["id"] for c in mine] == [created.json()["id"]]


def test_only_the_owner_can_manage_clone_knowledge(make_client, client: TestClient, registered: dict):
    clone_id = client.post(
        "/api/clones", json={"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}
    ).json()["id"]

    stranger = make_client()
    stranger.post("/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara"})
    # New clones are private, so strangers get 404 (existence isn't revealed).
    assert stranger.get(f"/api/clones/{clone_id}/documents").status_code == 404
    upload = stranger.post(f"/api/clones/{clone_id}/documents", files={"file": ("x.txt", b"hello", "text/plain")})
    assert upload.status_code == 404

    # Once public, visitors can see its chat profile but still can't manage it.
    open_to_public(client, clone_id)
    assert stranger.get(f"/api/clones/{clone_id}/chat-profile").status_code == 200
    assert stranger.get(f"/api/clones/{clone_id}/documents").status_code == 403
