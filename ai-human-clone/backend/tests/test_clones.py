import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.clone_prompt import build_clone_system_prompt
from app.models import CloneProfile, User
from app.services.slugs import slugify
from tests.conftest import USER, open_to_public

CLONE = {
    "name": "Ayaan AI",
    "tagline": "My digital AI version",
    "bio": "I am a software developer interested in AI.",
    "profession": "Software Developer",
    "skills": ["Python", "Django", "FastAPI", "AI"],
    "preferred_language": "Roman Urdu",
    "communication_style": "Friendly",
    "personality_description": "Explain things simply and communicate in a friendly style.",
    "response_length": "medium",
    "visibility": "private",
    "owner_consent": True,
}


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    """User A, logged in."""
    return client


@pytest.fixture
def other(make_client) -> TestClient:
    """User B, logged in with a separate cookie jar."""
    browser = make_client()
    response = browser.post(
        "/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara"}
    )
    assert response.status_code == 201
    return browser


def create(client: TestClient, **overrides) -> dict:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


# --- Create ---------------------------------------------------------------


def test_create_clone_returns_full_profile_with_server_fields(owner: TestClient):
    clone = create(owner)
    assert clone["name"] == "Ayaan AI"
    assert clone["slug"] == "ayaan-ai"
    assert clone["skills"] == ["Python", "Django", "FastAPI", "AI"]
    assert clone["status"] == "active"  # default
    assert clone["visibility"] == "private"
    assert clone["response_length"] == "medium"
    assert {"id", "created_at", "updated_at"} <= set(clone)
    assert "owner_id" not in clone and "owner_consent" not in clone


def test_ownership_is_assigned_from_the_session(owner: TestClient, db_session: Session, registered: dict):
    clone = create(owner)
    stored = db_session.get(CloneProfile, uuid.UUID(clone["id"]))
    assert str(stored.owner_id) == registered["id"]


def test_client_cannot_choose_owner_or_slug(owner: TestClient, other: TestClient):
    other_id = other.get("/api/auth/me").json()["id"]
    assert owner.post("/api/clones", json={**CLONE, "owner_id": other_id}).status_code == 400
    assert owner.post("/api/clones", json={**CLONE, "slug": "custom"}).status_code == 400


def test_unauthenticated_create_rejected(make_client):
    assert make_client().post("/api/clones", json=CLONE).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"visibility": "everyone"},
        {"response_length": "huge"},
        {"status": "deleted"},
        {"skills": "Python, Django"},  # must be a list
        {"skills": ["x" * 51]},
        {"skills": [f"skill{i}" for i in range(31)]},
        {"avatar_url": "javascript:alert(1)"},
        {"tagline": "t" * 161},
        {"owner_consent": False},
    ],
)
def test_invalid_data_rejected(owner: TestClient, overrides: dict):
    assert owner.post("/api/clones", json={**CLONE, **overrides}).status_code == 400


def test_skills_are_trimmed_and_deduplicated(owner: TestClient):
    clone = create(owner, skills=["  Python ", "python", "", "Docker"])
    assert clone["skills"] == ["Python", "Docker"]


def test_duplicate_names_get_unique_slugs(owner: TestClient, other: TestClient):
    first = create(owner)
    second = create(owner)
    third = create(other)  # slugs are unique across all users
    assert [first["slug"], second["slug"], third["slug"]] == ["ayaan-ai", "ayaan-ai-2", "ayaan-ai-3"]


def test_slugify_handles_symbols_and_non_latin_names():
    assert slugify("  Ayaan   AI!! ") == "ayaan-ai"
    assert slugify("Café Déjà Vu") == "cafe-deja-vu"
    assert slugify("آیان") == "clone"
    assert len(slugify("a" * 200)) == 60


# --- Read -------------------------------------------------------------------


def test_list_returns_only_my_clones(owner: TestClient, other: TestClient):
    mine = create(owner)
    create(other, name="Sara AI")
    listed = owner.get("/api/clones").json()
    assert [c["id"] for c in listed] == [mine["id"]]
    assert "bio" not in listed[0]  # list items are summaries


def test_list_requires_authentication(make_client):
    assert make_client().get("/api/clones").status_code == 401


def test_get_own_clone(owner: TestClient):
    clone = create(owner)
    response = owner.get(f"/api/clones/{clone['id']}")
    assert response.status_code == 200
    assert response.json()["bio"] == CLONE["bio"]


def test_other_user_cannot_see_private_clone(owner: TestClient, other: TestClient, make_client):
    clone = create(owner)
    # 404, not 403: a private clone's existence isn't revealed.
    assert other.get(f"/api/clones/{clone['id']}").status_code == 404
    assert other.get(f"/api/clones/{clone['id']}/chat-profile").status_code == 404
    assert make_client().get(f"/api/clones/{clone['id']}/chat-profile").status_code == 401  # login required


def test_other_user_cannot_manage_public_clone(owner: TestClient, other: TestClient):
    clone = create(owner, visibility="public")
    open_to_public(owner, clone["id"])
    assert other.get(f"/api/clones/{clone['id']}").status_code == 403
    profile = other.get(f"/api/clones/{clone['id']}/chat-profile")
    assert profile.status_code == 200
    assert profile.json()["is_owner"] is False
    assert "bio" not in profile.json() and "personality_description" not in profile.json()


def test_public_list_shows_only_public_active_clones(owner: TestClient, make_client):
    public = create(owner, name="Public AI", visibility="public")
    open_to_public(owner, public["id"])
    create(owner, name="Hidden AI", visibility="private")
    create(owner, name="Link AI", visibility="unlisted")
    create(owner, name="Off AI", visibility="public", status="disabled")
    create(owner, name="Closed AI", visibility="public")  # public chat not turned on
    listed = make_client().get("/api/clones/public").json()
    assert [c["id"] for c in listed] == [public["id"]]


# --- Update -----------------------------------------------------------------


def test_update_own_clone(owner: TestClient):
    clone = create(owner)
    response = owner.patch(
        f"/api/clones/{clone['id']}",
        json={"name": "Ayaan 2.0", "skills": ["Go"], "visibility": "unlisted", "tagline": None, "status": "draft"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ayaan 2.0"
    assert body["skills"] == ["Go"]
    assert body["visibility"] == "unlisted"
    assert body["status"] == "draft"
    assert body["tagline"] is None  # optional fields can be cleared
    assert body["bio"] == CLONE["bio"]  # untouched fields stay
    assert body["slug"] == "ayaan-ai"  # slug is stable so links keep working
    assert body["updated_at"] >= clone["updated_at"]


def test_update_ignores_null_for_required_fields(owner: TestClient):
    clone = create(owner)
    body = owner.patch(f"/api/clones/{clone['id']}", json={"name": None, "visibility": None}).json()
    assert body["name"] == "Ayaan AI" and body["visibility"] == "private"


def test_update_rejects_owner_change_and_bad_values(owner: TestClient, other: TestClient):
    clone = create(owner)
    other_id = other.get("/api/auth/me").json()["id"]
    assert owner.patch(f"/api/clones/{clone['id']}", json={"owner_id": other_id}).status_code == 400
    assert owner.patch(f"/api/clones/{clone['id']}", json={"slug": "new"}).status_code == 400
    assert owner.patch(f"/api/clones/{clone['id']}", json={"visibility": "open"}).status_code == 400
    assert owner.patch(f"/api/clones/{clone['id']}", json={"name": ""}).status_code == 400


def test_user_cannot_modify_another_users_clone(owner: TestClient, other: TestClient, db_session: Session):
    private = create(owner)
    public = create(owner, name="Public AI", visibility="public")
    assert other.patch(f"/api/clones/{private['id']}", json={"name": "Hacked"}).status_code == 404
    assert other.patch(f"/api/clones/{public['id']}", json={"name": "Hacked"}).status_code == 403
    names = set(db_session.scalars(select(CloneProfile.name)))
    assert "Hacked" not in names


# --- Delete -----------------------------------------------------------------


def test_delete_own_clone(owner: TestClient, qdrant):
    clone = create(owner)
    owner.post(f"/api/clones/{clone['id']}/knowledge", json={"title": "Note", "content": "Some memory about Python work."})
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone["id"])) > 0
    assert owner.delete(f"/api/clones/{clone['id']}").status_code == 204
    assert qdrant.count_chunks(clone_id=uuid.UUID(clone["id"])) == 0  # vectors removed too
    assert owner.get(f"/api/clones/{clone['id']}").status_code == 404
    assert owner.get("/api/clones").json() == []


def test_user_cannot_delete_another_users_clone(owner: TestClient, other: TestClient, make_client):
    private = create(owner)
    public = create(owner, name="Public AI", visibility="public")
    assert other.delete(f"/api/clones/{private['id']}").status_code == 404
    assert other.delete(f"/api/clones/{public['id']}").status_code == 403
    assert make_client().delete(f"/api/clones/{public['id']}").status_code == 401
    assert len(owner.get("/api/clones").json()) == 2


def test_deleting_a_user_removes_their_clones(owner: TestClient, db_session: Session):
    create(owner)
    user = db_session.scalar(select(User))
    db_session.delete(user)
    db_session.commit()
    assert db_session.scalar(select(CloneProfile)) is None


# --- Status and chat access -------------------------------------------------


def test_disabled_clone_cannot_chat_but_owner_can_still_manage(owner: TestClient, other: TestClient):
    clone = create(owner, visibility="public", status="disabled")
    open_to_public(owner, clone["id"])
    assert owner.get(f"/api/clones/{clone['id']}/chat-profile").status_code == 403
    response = other.post(f"/api/clones/{clone['id']}/chat", json={"message": "hi"})
    assert response.status_code == 403
    assert response.json()["detail"] == "This AI Clone is currently disabled."
    assert owner.get(f"/api/clones/{clone['id']}").status_code == 200
    assert owner.patch(f"/api/clones/{clone['id']}", json={"status": "active"}).status_code == 200
    assert other.get(f"/api/clones/{clone['id']}/chat-profile").status_code == 200


def test_draft_clone_is_only_chat_visible_to_owner(owner: TestClient, other: TestClient):
    clone = create(owner, visibility="public", status="draft")
    assert owner.get(f"/api/clones/{clone['id']}/chat-profile").json()["is_owner"] is True
    assert other.get(f"/api/clones/{clone['id']}/chat-profile").status_code == 404


# --- Prompt builder ---------------------------------------------------------


def test_system_prompt_contains_settings_and_ai_disclaimer():
    clone = CloneProfile(
        name="Ayaan AI",
        profession="Software Developer",
        skills=["Python", "FastAPI"],
        preferred_language="Roman Urdu",
        communication_style="Friendly",
        response_length="short",
        personality_description="Explain difficult concepts simply.",
    )
    prompt = build_clone_system_prompt(clone)
    for expected in ("Ayaan AI", "Software Developer", "Python, FastAPI", "Roman Urdu", "Friendly",
                     "Explain difficult concepts simply.", "one to three sentences"):
        assert expected in prompt
    assert "not the human person themselves" in prompt
    assert "Do not falsely claim to literally be the person" in prompt
