"""Phase 14: the public developer API endpoints under /api/v1 (API-key authenticated)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CloneProfile, Conversation, Document, Organization, OrganizationMember, UsageEvent, User
from tests.conftest import USER, tone_wav

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
CLONE = {
    "name": "Ayaan AI",
    "profession": "Software Developer",
    "skills": ["Python", "FastAPI"],
    "communication_style": "SECRET-STYLE-TEXT",
    "personality_description": "SECRET-PERSONALITY-TEXT",
    "owner_consent": True,
}
BACKEND_FACT = "I have worked with Python, Django and FastAPI on many backend projects."
HOBBY_FACT = "On weekends I play cricket and drink chai."
ALL_SCOPES = (
    "clone:read", "clone:chat", "clone:knowledge:read", "clone:search", "conversation:read",
    "conversation:write", "voice:transcribe", "voice:tts", "avatar:generate", "analytics:read",
)


def make_key(client: TestClient, scopes=("clone:read",), **extra) -> dict:
    response = client.post("/api/developer/keys", json={"name": "Website bot", "scopes": list(scopes), **extra})
    assert response.status_code == 201, response.text
    return response.json()


def api(client: TestClient, key: str, path: str = "/api/v1/me", method: str = "GET", **kwargs):
    return client.request(method, path, headers={"Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}, **kwargs)


def new_clone(client: TestClient, **overrides) -> str:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def teach(client: TestClient, clone_id: str, content: str, title: str) -> str:
    response = client.post(f"/api/clones/{clone_id}/knowledge", json={"title": title, "content": content})
    assert response.status_code == 201 and response.json()["indexing_status"] == "indexed", response.text
    return response.json()["id"]


def voice_on(client: TestClient, clone_id: str) -> None:
    assert client.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
    ).status_code == 200


def _org(db: Session, owner_email: str) -> Organization:
    owner = db.scalar(select(User).where(User.email == owner_email.lower()))
    org = Organization(name="Acme", slug="acme", owner_id=owner.id, is_active=True)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner", status="active"))
    db.commit()
    return org


@pytest.fixture(autouse=True)
def _generous_rate_limits(monkeypatch):
    """These tests make many calls with one key; rate limiting has its own tests."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "api_rate_limit_per_minute", 1000)
    monkeypatch.setattr(get_settings(), "api_rate_limit_per_hour", 10000)
    monkeypatch.setattr(get_settings(), "api_rate_limit_burst", 1000)


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def ext(make_client) -> TestClient:
    """A third-party app: no browser session, only the API key."""
    return make_client()


@pytest.fixture
def sara(make_client) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=SARA).status_code == 201
    return browser


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"] == code and body["message"] and body["request_id"].startswith("req_")


# --- Clones ---------------------------------------------------------------------------


def test_list_and_get_clones(owner: TestClient, ext: TestClient) -> None:
    clone_id = new_clone(owner)
    key = make_key(owner)["key"]
    listed = api(ext, key, "/api/v1/clones")
    assert listed.status_code == 200, listed.text
    data = listed.json()["data"]
    assert [c["id"] for c in data] == [clone_id]
    clone = api(ext, key, f"/api/v1/clones/{clone_id}").json()
    assert clone["name"] == "Ayaan AI" and clone["skills"] == ["Python", "FastAPI"]
    assert {"id", "name", "slug", "status", "visibility", "voice_enabled", "avatar_enabled", "created_at"} <= set(clone)
    text = json.dumps([data, clone])
    assert "SECRET-STYLE-TEXT" not in text and "SECRET-PERSONALITY-TEXT" not in text
    assert "system_prompt" not in text and "owner_id" not in text
    assert_error(api(ext, key, f"/api/v1/clones/{uuid.uuid4()}"), 404, "resource_not_found")


def test_cross_user_access_is_not_found(owner: TestClient, sara: TestClient, ext: TestClient) -> None:
    mine = new_clone(owner)
    owner_key = make_key(owner, scopes=ALL_SCOPES)["key"]
    reply = api(ext, owner_key, f"/api/v1/clones/{mine}/chat", "POST", json={"message": "Hello"}).json()
    sara_clone = new_clone(sara, name="Sara AI")
    sara_key = make_key(sara, scopes=ALL_SCOPES)["key"]

    assert [c["id"] for c in api(ext, sara_key, "/api/v1/clones").json()["data"]] == [sara_clone]
    for method, path, body in (
        ("GET", f"/api/v1/clones/{mine}", None),
        ("POST", f"/api/v1/clones/{mine}/chat", {"message": "hi"}),
        ("GET", f"/api/v1/clones/{mine}/conversations", None),
        ("GET", f"/api/v1/conversations/{reply['conversation_id']}", None),
        ("DELETE", f"/api/v1/conversations/{reply['conversation_id']}", None),
        ("POST", f"/api/v1/clones/{mine}/search", {"query": "python"}),
        ("POST", f"/api/v1/clones/{mine}/voice/tts", {"text": "hi"}),
        ("GET", f"/api/v1/clones/{mine}/analytics/overview", None),
        ("GET", f"/api/v1/clones/{mine}/analytics/activity", None),
        ("POST", f"/api/v1/clones/{mine}/avatar/video", {"text": "hi"}),
        ("GET", f"/api/v1/clones/{mine}/avatar/jobs/{uuid.uuid4()}", None),
    ):
        assert_error(api(ext, sara_key, path, method, json=body), 404, "resource_not_found")
    # Sara's key can't continue the owner's conversation through her own clone either.
    response = api(ext, sara_key, f"/api/v1/clones/{sara_clone}/chat", "POST",
                   json={"message": "hi", "conversation_id": reply["conversation_id"]})
    assert_error(response, 404, "resource_not_found")


def test_organization_key_reaches_only_org_clones(owner: TestClient, ext: TestClient, db_session: Session) -> None:
    personal = new_clone(owner)
    org_clone = new_clone(owner, name="Acme Support")
    org = _org(db_session, USER["email"])
    row = db_session.get(CloneProfile, uuid.UUID(org_clone))
    row.organization_id = org.id
    db_session.commit()
    key = make_key(owner, scopes=("clone:read", "clone:chat"), organization_id=str(org.id))["key"]
    assert [c["id"] for c in api(ext, key, "/api/v1/clones").json()["data"]] == [org_clone]
    assert_error(api(ext, key, f"/api/v1/clones/{personal}"), 404, "resource_not_found")
    chat = api(ext, key, f"/api/v1/clones/{org_clone}/chat", "POST", json={"message": "Hello there"})
    assert chat.status_code == 200, chat.text
    event = db_session.scalar(select(UsageEvent).where(UsageEvent.event_type == "API_CHAT"))
    assert event.organization_id == org.id and event.user_id is None


# --- Chat and conversations -----------------------------------------------------------


def test_chat_with_rag_sources_and_usage(owner: TestClient, ext: TestClient, db_session: Session, llm) -> None:
    clone_id = new_clone(owner)
    teach(owner, clone_id, BACKEND_FACT, "My CV")
    teach(owner, clone_id, HOBBY_FACT, "Hobbies")
    created = make_key(owner, scopes=("clone:chat", "conversation:read", "conversation:write"))
    key = created["key"]
    response = api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST",
                   json={"message": "What backend technologies have you worked with?", "conversation_id": None})
    assert response.status_code == 200, response.text
    body = response.json()
    assert BACKEND_FACT in llm.calls[-1]["context"]
    assert all(tech in body["message"] for tech in ("Python", "Django", "FastAPI"))
    assert [s["title"] for s in body["sources"]] == ["My CV"]
    assert set(body["sources"][0]) == {"title", "score"}
    assert {"conversation_id", "message_id", "message", "sources", "memories_used"} <= set(body)
    assert "SECRET-PERSONALITY-TEXT" not in json.dumps(body) and "system" not in json.dumps(body)

    # Continue the same conversation.
    again = api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST",
                json={"message": "And which hobbies?", "conversation_id": body["conversation_id"]})
    assert again.status_code == 200 and again.json()["conversation_id"] == body["conversation_id"]

    # Saved: readable through the API, with roles and content.
    conversation = api(ext, key, f"/api/v1/conversations/{body['conversation_id']}").json()
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant", "user", "assistant"]
    assert conversation["messages"][0]["content"] == "What backend technologies have you worked with?"
    listed = api(ext, key, f"/api/v1/clones/{clone_id}/conversations").json()["data"]
    assert [c["id"] for c in listed] == [body["conversation_id"]]

    # Usage: one API_CHAT per turn, attributed to the key and clone, no message text.
    db_session.expire_all()
    events = list(db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "API_CHAT")))
    assert len(events) == 2
    assert all(str(e.api_key_id) == created["id"] and str(e.clone_id) == clone_id for e in events)
    requests = list(db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "API_REQUEST")))
    assert requests and all(str(e.clone_id) == clone_id for e in requests if "clones" in (e.endpoint or ""))
    everything = str([(e.endpoint, e.provider, e.status) for e in db_session.scalars(select(UsageEvent))])
    assert "backend technologies" not in everything and key not in everything

    # Delete.
    assert api(ext, key, f"/api/v1/conversations/{body['conversation_id']}", "DELETE").status_code == 204
    assert db_session.get(Conversation, uuid.UUID(body["conversation_id"])) is None
    assert_error(api(ext, key, f"/api/v1/conversations/{body['conversation_id']}"), 404, "resource_not_found")


def test_chat_validation_and_limits(owner: TestClient, ext: TestClient, monkeypatch) -> None:
    from app.developer import limits

    clone_id = new_clone(owner)
    key = make_key(owner, scopes=("clone:chat",))["key"]
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "  "}), 400, "validation_error")
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "hi", "x": 1}),
                 400, "validation_error")
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST",
                     json={"message": "hi", "conversation_id": str(uuid.uuid4())}), 404, "resource_not_found")

    monkeypatch.setitem(limits._DEFAULTS["free"], "chat_messages", 1)
    assert api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "hello"}).status_code == 200
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "again"}),
                 429, "usage_limit_reached")


def test_conversation_must_belong_to_the_clone(owner: TestClient, ext: TestClient) -> None:
    first, second = new_clone(owner), new_clone(owner, name="Second AI")
    key = make_key(owner, scopes=("clone:chat",))["key"]
    reply = api(ext, key, f"/api/v1/clones/{first}/chat", "POST", json={"message": "hello"}).json()
    response = api(ext, key, f"/api/v1/clones/{second}/chat", "POST",
                   json={"message": "hi", "conversation_id": reply["conversation_id"]})
    assert_error(response, 404, "resource_not_found")


def test_disabled_clone_cannot_chat(owner: TestClient, ext: TestClient, db_session: Session) -> None:
    clone_id = new_clone(owner)
    row = db_session.get(CloneProfile, uuid.UUID(clone_id))
    row.status = "disabled"
    db_session.commit()
    key = make_key(owner, scopes=("clone:chat",))["key"]
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "hi"}), 403, "permission_denied")


# --- Scopes -----------------------------------------------------------------------------


def test_every_endpoint_enforces_its_scope(owner: TestClient, ext: TestClient) -> None:
    clone_id = new_clone(owner)
    conversation = str(uuid.uuid4())
    job = str(uuid.uuid4())
    audio = "a" * 32
    endpoints = [
        ("GET", "/api/v1/clones", None, "clone:read"),
        ("GET", f"/api/v1/clones/{clone_id}", None, "clone:read"),
        ("POST", f"/api/v1/clones/{clone_id}/chat", {"message": "hi"}, "clone:chat"),
        ("GET", f"/api/v1/clones/{clone_id}/conversations", None, "conversation:read"),
        ("GET", f"/api/v1/conversations/{conversation}", None, "conversation:read"),
        ("DELETE", f"/api/v1/conversations/{conversation}", None, "conversation:write"),
        ("POST", f"/api/v1/clones/{clone_id}/search", {"query": "python"}, "clone:search"),
        ("POST", f"/api/v1/clones/{clone_id}/voice/tts", {"text": "hi"}, "voice:tts"),
        ("GET", f"/api/v1/clones/{clone_id}/voice/audio/{audio}", None, "voice:tts"),
        ("POST", f"/api/v1/clones/{clone_id}/avatar/video", {"text": "hi"}, "avatar:generate"),
        ("GET", f"/api/v1/clones/{clone_id}/avatar/jobs/{job}", None, "avatar:generate"),
        ("GET", f"/api/v1/clones/{clone_id}/avatar/jobs/{job}/video", None, "avatar:generate"),
        ("GET", f"/api/v1/clones/{clone_id}/analytics/overview", None, "analytics:read"),
        ("GET", f"/api/v1/clones/{clone_id}/analytics/activity", None, "analytics:read"),
    ]
    for method, path, body, scope in endpoints:
        others = tuple(s for s in ALL_SCOPES if s != scope and not (scope == "clone:search" and s == "clone:knowledge:read"))
        key = make_key(owner, scopes=others)["key"]
        response = api(ext, key, path, method, json=body)
        assert_error(response, 403, "permission_denied")
        assert scope in response.json()["message"], (path, response.json())

    # Multipart voice endpoints.
    no_transcribe = make_key(owner, scopes=tuple(s for s in ALL_SCOPES if s != "voice:transcribe"))["key"]
    files = {"audio": ("hello.wav", tone_wav(), "audio/wav")}
    assert_error(api(ext, no_transcribe, f"/api/v1/clones/{clone_id}/voice/transcribe", "POST", files=files),
                 403, "permission_denied")
    for missing in ("voice:transcribe", "voice:tts", "clone:chat"):
        key = make_key(owner, scopes=tuple(s for s in ALL_SCOPES if s != missing))["key"]
        response = api(ext, key, f"/api/v1/clones/{clone_id}/voice/chat", "POST", files=files)
        assert_error(response, 403, "permission_denied")


# --- Search -------------------------------------------------------------------------------


def test_search_all_vs_public_only(owner: TestClient, ext: TestClient, db_session: Session) -> None:
    clone_id = new_clone(owner)
    private_doc = teach(owner, clone_id, BACKEND_FACT, "Private CV")
    public_doc = teach(owner, clone_id, "Public note: I have worked with Python on open source projects.", "Public note")
    db_session.get(Document, uuid.UUID(public_doc)).visibility = "public"
    db_session.commit()
    assert db_session.get(Document, uuid.UUID(private_doc)).visibility == "private"

    full = make_key(owner, scopes=("clone:search",))["key"]
    public = make_key(owner, scopes=("clone:knowledge:read",))["key"]
    query = {"query": "Which projects have you worked on with Python?", "top_k": 5}

    everything = api(ext, full, f"/api/v1/clones/{clone_id}/search", "POST", json=query)
    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert body["scope"] == "all" and {r["title"] for r in body["results"]} == {"Private CV", "Public note"}
    for result in body["results"]:
        assert set(result) == {"title", "source_type", "score", "snippet"} and len(result["snippet"]) <= 500

    limited = api(ext, public, f"/api/v1/clones/{clone_id}/search", "POST", json=query).json()
    assert limited["scope"] == "public" and [r["title"] for r in limited["results"]] == ["Public note"]
    assert "Django" not in json.dumps(limited)

    assert_error(api(ext, full, f"/api/v1/clones/{clone_id}/search", "POST", json={"query": ""}), 400, "validation_error")


def test_search_snippets_are_trimmed(owner: TestClient, ext: TestClient) -> None:
    clone_id = new_clone(owner)
    teach(owner, clone_id, "Python " * 150 + "is what I use every day for backend work.", "Long")
    key = make_key(owner, scopes=("clone:search",))["key"]
    results = api(ext, key, f"/api/v1/clones/{clone_id}/search", "POST", json={"query": "Python backend"}).json()["results"]
    assert results and all(len(r["snippet"]) <= 500 for r in results)


def test_search_without_knowledge_is_empty(owner: TestClient, ext: TestClient, db_session: Session) -> None:
    clone_id = new_clone(owner)
    key = make_key(owner, scopes=("clone:search",))["key"]
    response = api(ext, key, f"/api/v1/clones/{clone_id}/search", "POST", json={"query": "anything"})
    assert response.status_code == 200 and response.json()["results"] == []


# --- Voice --------------------------------------------------------------------------------


def test_voice_transcribe_tts_and_audio(owner: TestClient, ext: TestClient, db_session: Session, stt, tts) -> None:
    clone_id = new_clone(owner)
    key = make_key(owner, scopes=("voice:transcribe", "voice:tts", "clone:chat"))["key"]
    files = {"audio": ("hello.wav", tone_wav(), "audio/wav")}

    # Voice off: a clear 403.
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/voice/tts", "POST", json={"text": "Hello"}),
                 403, "permission_denied")

    voice_on(owner, clone_id)
    transcribed = api(ext, key, f"/api/v1/clones/{clone_id}/voice/transcribe", "POST", files=files)
    assert transcribed.status_code == 200, transcribed.text
    assert transcribed.json()["text"] == stt.text

    spoken = api(ext, key, f"/api/v1/clones/{clone_id}/voice/tts", "POST", json={"text": "Hello from the API"})
    assert spoken.status_code == 200, spoken.text
    url = spoken.json()["audio_url"]
    assert url.startswith(f"/api/v1/clones/{clone_id}/voice/audio/") and "storage" not in url
    assert tts.calls[-1]["text"] == "Hello from the API"
    audio = api(ext, key, url)
    assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/") and len(audio.content) > 100
    assert ext.get(url).status_code == 401  # needs the key
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/voice/audio/{'b' * 32}"), 404, "resource_not_found")
    assert api(ext, key, f"/api/v1/clones/{clone_id}/voice/audio/..%2F..%2Fsecret").status_code == 404

    chat = api(ext, key, f"/api/v1/clones/{clone_id}/voice/chat", "POST", files=files)
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["transcript"] == stt.text and body["answer"]
    assert body["audio_url"].startswith(f"/api/v1/clones/{clone_id}/voice/audio/")
    assert api(ext, key, body["audio_url"]).status_code == 200

    db_session.expire_all()
    assert len(list(db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "API_VOICE")))) == 3


def test_voice_plan_limit(owner: TestClient, ext: TestClient, monkeypatch) -> None:
    from app.developer import limits

    clone_id = new_clone(owner)
    voice_on(owner, clone_id)
    monkeypatch.setitem(limits._DEFAULTS["free"], "tts_requests", 1)
    key = make_key(owner, scopes=("voice:tts",))["key"]
    assert api(ext, key, f"/api/v1/clones/{clone_id}/voice/tts", "POST", json={"text": "one"}).status_code == 200
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/voice/tts", "POST", json={"text": "two"}),
                 429, "usage_limit_reached")


def test_voice_provider_not_configured(owner: TestClient, ext: TestClient, monkeypatch) -> None:
    from app.voice.base import VoiceNotConfiguredError

    clone_id = new_clone(owner)
    voice_on(owner, clone_id)

    def unconfigured():
        raise VoiceNotConfiguredError("no provider")

    monkeypatch.setattr("app.voice.factory.get_tts_provider", unconfigured)
    key = make_key(owner, scopes=("voice:tts",))["key"]
    response = api(ext, key, f"/api/v1/clones/{clone_id}/voice/tts", "POST", json={"text": "hello"})
    assert_error(response, 503, "provider_unavailable")


# --- Avatar -------------------------------------------------------------------------------


def test_avatar_video_job(owner: TestClient, ext: TestClient, db_session: Session) -> None:
    clone_id = new_clone(owner)
    key = make_key(owner, scopes=("avatar:generate", "clone:chat"))["key"]
    # Without consent / avatar: refused by the service rules.
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/avatar/video", "POST", json={"text": "Hello"}),
                 403, "permission_denied")
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/avatar/video", "POST", json={}), 400, "validation_error")

    voice_on(owner, clone_id)
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_consent_given": True}).status_code == 200
    assert owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "ayaan"}).status_code == 201
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True}).status_code == 200

    created = api(ext, key, f"/api/v1/clones/{clone_id}/avatar/video", "POST", json={"text": "Hello from the API"})
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    job = api(ext, key, f"/api/v1/clones/{clone_id}/avatar/jobs/{job_id}").json()
    assert job["status"] == "completed", job
    assert job["video_url"] == f"/api/v1/clones/{clone_id}/avatar/jobs/{job_id}/video"
    assert "provider" not in job and "storage" not in json.dumps(job)
    video = api(ext, key, job["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and len(video.content) > 100

    # An answer video for an API conversation.
    reply = api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "Hello"}).json()
    answer = api(ext, key, f"/api/v1/clones/{clone_id}/avatar/video", "POST",
                 json={"conversation_id": reply["conversation_id"], "message_id": reply["message_id"]})
    assert answer.status_code == 202, answer.text
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/avatar/jobs/{uuid.uuid4()}"), 404, "resource_not_found")
    db_session.expire_all()
    assert len(list(db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "API_AVATAR")))) == 2


# --- Analytics ----------------------------------------------------------------------------


def test_analytics_overview_and_activity(owner: TestClient, ext: TestClient) -> None:
    clone_id = new_clone(owner)
    teach(owner, clone_id, BACKEND_FACT, "My CV")
    key = make_key(owner, scopes=("analytics:read", "clone:chat"))["key"]
    api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "SECRET-QUESTION about Python"})

    overview = api(ext, key, f"/api/v1/clones/{clone_id}/analytics/overview?range=7d")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["range"] == "7d" and body["total_conversations"] == 1 and body["total_messages"] == 2
    assert body["total_documents"] == 1

    activity = api(ext, key, f"/api/v1/clones/{clone_id}/analytics/activity?range=7d")
    assert activity.status_code == 200, activity.text
    days = activity.json()["days"]
    assert len(days) == 8 and sum(d["messages"] for d in days) == 2 and sum(d["conversations"] for d in days) == 1
    assert "SECRET-QUESTION" not in overview.text + activity.text
    assert_error(api(ext, key, f"/api/v1/clones/{clone_id}/analytics/overview?range=forever"), 400, "validation_error")


def test_analytics_overview_without_events_table(owner: TestClient, ext: TestClient, monkeypatch) -> None:
    from app.api.v1 import analytics

    monkeypatch.setattr(analytics, "_events_table_exists", lambda db: False)
    clone_id = new_clone(owner)
    key = make_key(owner, scopes=("analytics:read", "clone:chat"))["key"]
    api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "hello"})
    body = api(ext, key, f"/api/v1/clones/{clone_id}/analytics/overview").json()
    assert body["range"] == "30d" and body["total_conversations"] == 1 and body["total_messages"] == 2


# --- Format, secrets, OpenAPI -------------------------------------------------------------


def test_error_format_and_no_secrets(owner: TestClient, ext: TestClient) -> None:
    clone_id = new_clone(owner)
    created = make_key(owner, scopes=ALL_SCOPES)
    key = created["key"]
    missing = ext.get("/api/v1/clones")
    assert_error(missing, 401, "authentication_failed")
    assert set(missing.json()) == {"error", "message", "request_id"}
    bad_id = api(ext, key, "/api/v1/clones/not-a-uuid")
    assert_error(bad_id, 400, "validation_error")
    responses = [
        api(ext, key, "/api/v1/clones"),
        api(ext, key, f"/api/v1/clones/{clone_id}"),
        api(ext, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "hello"}),
    ]
    for response in responses:
        assert response.status_code == 200
        assert key not in response.text and created["key_prefix"] not in response.text
        assert "SECRET-PERSONALITY-TEXT" not in response.text and "/app/" not in response.text


def test_openapi_lists_the_endpoints(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()
    paths = schema["paths"]
    for path in (
        "/api/v1/clones",
        "/api/v1/clones/{clone_id}",
        "/api/v1/clones/{clone_id}/chat",
        "/api/v1/clones/{clone_id}/conversations",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/clones/{clone_id}/search",
        "/api/v1/clones/{clone_id}/voice/transcribe",
        "/api/v1/clones/{clone_id}/voice/chat",
        "/api/v1/clones/{clone_id}/voice/tts",
        "/api/v1/clones/{clone_id}/voice/audio/{audio_id}",
        "/api/v1/clones/{clone_id}/avatar/video",
        "/api/v1/clones/{clone_id}/avatar/jobs/{job_id}",
        "/api/v1/clones/{clone_id}/avatar/jobs/{job_id}/video",
        "/api/v1/clones/{clone_id}/analytics/overview",
        "/api/v1/clones/{clone_id}/analytics/activity",
    ):
        assert path in paths, path
    assert "delete" in paths["/api/v1/conversations/{conversation_id}"]
    assert paths["/api/v1/clones/{clone_id}/chat"]["post"]["tags"] == ["Chat"]
    assert "ApiChatResponse" in schema["components"]["schemas"]
