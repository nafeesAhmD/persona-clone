"""Phase 20 security audit: route protection, cross-user isolation, and the fixes it found."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.conftest import USER

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
CLONE = {
    "name": "Ayaan AI",
    "profession": "Software Developer",
    "skills": ["Python"],
    "personality_description": "SECRET-PERSONALITY-TEXT",
    "owner_consent": True,
}
PRIVATE_FACT = "SECRET-KNOWLEDGE: my bank PIN reminder is under the blue mug."

# Every route reachable without a user session, an admin session or an API key.
# Adding a public route means adding it here on purpose.
PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/health"),
    ("GET", "/api/health/live"),
    ("GET", "/api/health/ready"),
    ("GET", "/api/health/services"),
    ("GET", "/api/health/qdrant"),
    ("GET", "/api/mobile/config"),
    ("GET", "/api/platform/status"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/register"),
    ("GET", "/api/billing/plans"),
    ("POST", "/api/billing/webhooks/{provider}"),  # a stub that changes nothing
    ("GET", "/api/clones/public"),
    ("GET", "/api/developer/keys/scopes"),
    ("GET", "/api/developer/webhooks/events"),
    ("GET", "/api/v1/openapi.json"),
    ("GET", "/api/v1/docs"),
    # Public clones and the marketplace (visitor session token checked inside).
    ("GET", "/api/public/clones"),
    ("GET", "/api/public/clones/{slug}"),
    ("GET", "/api/public/clones/{slug}/avatar-image"),
    ("GET", "/api/public/clones/{slug}/session"),
    ("DELETE", "/api/public/clones/{slug}/session"),
    ("POST", "/api/public/clones/{slug}/chat"),
    ("POST", "/api/public/clones/{slug}/voice/transcribe"),
    ("POST", "/api/public/clones/{slug}/messages/{message_id}/speech"),
    ("GET", "/api/public/clones/{slug}/audio/{audio_id}"),
    ("POST", "/api/public/clones/{slug}/messages/{message_id}/avatar"),
    ("GET", "/api/public/clones/{slug}/avatar/jobs/{job_id}"),
    ("GET", "/api/public/clones/{slug}/avatar/jobs/{job_id}/video"),
    ("POST", "/api/public/clones/{slug}/realtime/session"),
    ("POST", "/api/public/clones/{slug}/realtime/session/{session_id}/end"),
    ("GET", "/api/marketplace/clones"),
    ("GET", "/api/marketplace/search"),
    ("GET", "/api/marketplace/categories"),
    ("GET", "/api/marketplace/tags"),
    ("GET", "/api/marketplace/clones/featured"),
    ("GET", "/api/marketplace/clones/{slug}"),
    ("POST", "/api/marketplace/clones/{slug}/report"),
    # The real-time voice socket authenticates with its one-time ticket.
    ("WS", "/api/realtime/sessions/{session_id}/ws"),
}
AUTH_DEPENDENCIES = {"get_current_user", "require_admin", "get_api_principal"}


def _dependencies(dependant, found: set[str]) -> set[str]:
    for sub in getattr(dependant, "dependencies", None) or []:
        found.add(getattr(sub.call, "__name__", type(sub.call).__name__))
        _dependencies(sub, found)
    return found


def all_routes() -> list[tuple[str, str, set[str]]]:
    """(method, path, dependency names) for every route, including nested routers
    (FastAPI keeps those as included-router contexts, not flat APIRoutes)."""
    out: list[tuple[str, str, set[str]]] = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            items = contexts() if callable(contexts) else contexts
        elif getattr(route, "dependant", None) is not None:
            items = [route]
        else:
            continue  # framework docs pages (/docs, /openapi.json…)
        for item in items:
            deps = _dependencies(getattr(item, "dependant", None), set())
            methods = getattr(item, "methods", None) or {"WS"}
            path = getattr(item, "path_format", None) or item.path
            if not path:  # WebSocket contexts keep only the router-relative path; all routers sit under /api
                path = "/api" + getattr(getattr(item, "original_route", None), "path", "")
            out.extend((method, path, deps) for method in methods if method != "HEAD")
    return out


def test_every_non_public_route_requires_authentication():
    routes = all_routes()
    assert len(routes) > 200  # the walk really saw the nested routers
    unprotected = sorted(
        (method, path) for method, path, deps in routes
        if not deps & AUTH_DEPENDENCIES and (method, path) not in PUBLIC_ROUTES
    )
    assert unprotected == [], f"routes without authentication: {unprotected}"


def test_admin_routes_all_require_admin():
    for method, path, deps in all_routes():
        if path.startswith("/api/admin/"):
            assert "require_admin" in deps, (method, path)


# --- Two users ---------------------------------------------------------------


@pytest.fixture
def ayaan(make_client) -> TestClient:
    client = make_client()
    assert client.post("/api/auth/register", json=USER).status_code == 201
    return client


@pytest.fixture
def sara(make_client) -> TestClient:
    client = make_client()
    assert client.post("/api/auth/register", json=SARA).status_code == 201
    return client


@pytest.fixture
def ayaans_data(ayaan: TestClient) -> dict:
    clone = ayaan.post("/api/clones", json=CLONE)
    assert clone.status_code == 201, clone.text
    clone_id = clone.json()["id"]
    doc = ayaan.post(f"/api/clones/{clone_id}/knowledge", json={"title": "Private note", "content": PRIVATE_FACT})
    assert doc.status_code == 201, doc.text
    chat = ayaan.post(f"/api/clones/{clone_id}/chat", json={"message": "What is under the blue mug?"})
    assert chat.status_code == 200, chat.text
    assert ayaan.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
    ).status_code == 200
    audio = ayaan.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hello"})
    assert audio.status_code == 200, audio.text
    key = ayaan.post("/api/developer/keys", json={"name": "Bot", "scopes": ["clone:read"]})
    assert key.status_code == 201, key.text
    return {
        "clone_id": clone_id,
        "document_id": doc.json()["id"],
        "conversation_id": chat.json()["conversation_id"],
        "audio_url": audio.json()["audio_url"],
        "key_id": key.json()["id"],
        "key_secret": key.json()["key"],
    }


def _fill(path: str, data: dict) -> str:
    ids = {
        "clone_id": data["clone_id"],
        "document_id": data["document_id"],
        "conversation_id": data["conversation_id"],
        "key_id": data["key_id"],
    }
    return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


def test_another_user_cannot_read_anything_of_a_private_clone(ayaans_data: dict, sara: TestClient):
    checked = 0
    for method, path, deps in all_routes():
        if method != "GET" or "{clone_id}" not in path or "get_current_user" not in deps:
            continue
        if path.startswith(("/api/admin/", "/api/organizations/")):
            continue
        url = _fill(path, ayaans_data)
        response = sara.get(url)
        assert response.status_code in (403, 404), (url, response.status_code, response.text[:200])
        assert "SECRET" not in response.text, url
        checked += 1
    assert checked >= 20


def test_another_user_cannot_change_or_use_a_private_clone(ayaans_data: dict, ayaan: TestClient, sara: TestClient):
    clone_id = ayaans_data["clone_id"]
    attempts = [
        sara.patch(f"/api/clones/{clone_id}", json={"name": "Hacked"}),
        sara.delete(f"/api/clones/{clone_id}"),
        sara.post(
            f"/api/clones/{clone_id}/knowledge",
            json={"title": "Injected note", "content": "This text was written by someone who does not own the clone."},
        ),
        sara.delete(f"/api/clones/{clone_id}/documents/{ayaans_data['document_id']}"),
        sara.post(f"/api/clones/{clone_id}/chat", json={"message": "What is under the blue mug?"}),
        sara.patch(f"/api/clones/{clone_id}/public-settings", json={"visibility": "public"}),
        sara.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_enabled": False}),
        sara.post(f"/api/clones/{clone_id}/voice/test", json={"text": "hi"}),
        sara.patch(f"/api/clones/{clone_id}/marketplace", json={"enabled": True, "confirm_publish": True}),
        sara.post(f"/api/clones/{clone_id}/realtime/session", json={}),
        sara.delete(f"/api/conversations/{ayaans_data['conversation_id']}"),
    ]
    for response in attempts:
        assert response.status_code in (403, 404), (response.request.method, response.request.url, response.status_code)
        assert "SECRET" not in response.text
    mine = ayaan.get(f"/api/clones/{clone_id}").json()
    assert mine["name"] == "Ayaan AI" and mine["visibility"] == "private"
    assert ayaan.get(f"/api/conversations/{ayaans_data['conversation_id']}").status_code == 200


def test_another_user_cannot_fetch_someone_elses_audio(ayaans_data: dict, ayaan: TestClient, sara: TestClient):
    url = ayaans_data["audio_url"]
    assert ayaan.get(url).status_code == 200
    assert sara.get(url).status_code == 404


def test_api_keys_are_private_and_hashed(ayaans_data: dict, sara: TestClient, db_session: Session):
    from sqlalchemy import select

    from app.models import ApiKey

    key_id, secret = ayaans_data["key_id"], ayaans_data["key_secret"]
    assert sara.get(f"/api/developer/keys/{key_id}").status_code == 404
    assert sara.delete(f"/api/developer/keys/{key_id}").status_code == 404
    assert all(k["id"] != key_id for k in sara.get("/api/developer/keys").json())
    stored = db_session.scalar(select(ApiKey).where(ApiKey.id == uuid.UUID(key_id)))
    assert secret not in str({c.name: getattr(stored, c.name) for c in stored.__table__.columns})


def test_logged_out_users_get_401(ayaans_data: dict, make_client):
    stranger = make_client()
    clone_id = ayaans_data["clone_id"]
    for url in (f"/api/clones/{clone_id}", f"/api/clones/{clone_id}/documents", "/api/developer/keys",
                f"/api/conversations/{ayaans_data['conversation_id']}", ayaans_data["audio_url"]):
        assert stranger.get(url).status_code == 401, url


def test_non_admins_are_refused_by_admin_endpoints(sara: TestClient):
    for url in ("/api/admin/users", "/api/admin/clones", "/api/admin/marketplace/reports", "/api/admin/audit-logs"):
        assert sara.get(url).status_code in (403, 404), url


# --- Fix F-1: changing the password ends every other session -----------------


def test_password_change_revokes_older_sessions(make_client):
    laptop, phone = make_client(), make_client()
    assert laptop.post("/api/auth/register", json=USER).status_code == 201
    assert phone.post("/api/auth/login", json={"email": USER["email"], "password": USER["password"]}).status_code == 200
    assert phone.get("/api/auth/me").status_code == 200

    import time

    time.sleep(1.1)  # token "iat" has one-second resolution
    changed = laptop.post(
        "/api/auth/change-password",
        json={"current_password": USER["password"], "new_password": "AnotherStrongPass456!"},
    )
    assert changed.status_code == 204, changed.text
    # The device that changed the password gets a fresh session; the other one is out.
    assert laptop.get("/api/auth/me").status_code == 200
    assert phone.get("/api/auth/me").status_code == 401
    assert phone.get("/api/clones").status_code == 401
    # And the stolen/old token can no longer keep itself alive through /me renewals.
    again = make_client()
    assert again.post("/api/auth/login", json={"email": USER["email"], "password": "AnotherStrongPass456!"}).status_code == 200
    assert again.get("/api/auth/me").status_code == 200


# --- Fix F-2: the LLM check needs a session -----------------------------------


def test_llm_health_requires_login(make_client, client: TestClient, registered):
    assert make_client().get("/api/health/llm").status_code == 401
    assert client.get("/api/health/llm").status_code == 200


# --- Fix F-3: the public list doesn't reveal private knowledge counts ---------


def test_public_list_hides_knowledge_counts(ayaan: TestClient, make_client):
    clone_id = ayaan.post("/api/clones", json=CLONE).json()["id"]
    assert ayaan.post(f"/api/clones/{clone_id}/knowledge", json={"title": "n", "content": PRIVATE_FACT}).status_code == 201
    assert ayaan.patch(
        f"/api/clones/{clone_id}/public-settings", json={"visibility": "public", "public_chat_enabled": True}
    ).status_code == 200
    [card] = make_client().get("/api/clones/public").json()
    assert card["id"] == clone_id
    assert (card["knowledge_count"], card["indexed_count"], card["chunk_count"]) == (0, 0, 0)
    assert ayaan.get("/api/clones").json()[0]["knowledge_count"] == 1  # the owner still sees them
