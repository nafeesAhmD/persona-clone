"""Phase 17: real-time voice — settings, sessions, the WebSocket protocol, limits and safety.

STT, LLM and TTS are the conftest fakes (no paid services). Protocol and errors:
docs/phase17/contract.md.
"""

import json
import logging
import uuid
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.ai.base import LLMRateLimitError
from app.billing import service as billing_service
from app.core.config import get_settings
from app.models import AnalyticsEvent, CloneProfile, Conversation, Message, RealtimeVoiceSession, UsageEvent, User
from app.realtime_voice import service as realtime_service
from app.realtime_voice.providers import pipeline
from app.realtime_voice.session_manager import manager
from app.voice.base import VoiceUnavailableError
from tests.conftest import USER, open_to_public, tone_wav
from tests.test_public import add_document, add_memory, everything_sent
from tests.test_voice import enable_voice, new_clone

ORIGIN = "http://localhost:3007"
WAV = tone_wav(1.0)


@pytest.fixture(autouse=True)
def realtime_on(monkeypatch, db_session: Session):
    settings = get_settings()
    monkeypatch.setattr(settings, "realtime_voice_enabled", True)
    monkeypatch.setattr("app.realtime_voice.db.SessionLocal", lambda: nullcontext(db_session))
    realtime_service.session_limiter.reset()
    manager.clear()
    yield settings
    manager.clear()


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def other(make_client) -> TestClient:
    browser = make_client()
    assert browser.post(
        "/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
    ).status_code == 201
    return browser


def start(client: TestClient, clone_id: str, **body):
    return client.post(f"/api/clones/{clone_id}/realtime/session", json=body or None)


def created(client: TestClient, clone_id: str, **body) -> dict:
    response = start(client, clone_id, **body)
    assert response.status_code == 201, response.text
    return response.json()


def connect(client: TestClient, session: dict, *, origin: str | None = ORIGIN, ticket: str | None = None):
    headers = {"origin": origin} if origin else {}
    return client.websocket_connect(f"{session['ws_path']}?ticket={ticket or session['ticket']}", headers=headers)


def collect(ws, until: str = "turn_done", turn: int | None = None) -> list[dict]:
    """Messages up to (and including) the first `until` (of `turn`). Binary frames appear
    as {"type": "binary", "size", "head"}."""
    out: list[dict] = []
    while True:
        message = ws.receive()
        if message.get("text") is not None:
            data = json.loads(message["text"])
            out.append(data)
            if data["type"] == until and (turn is None or data.get("turn") == turn):
                return out
        elif message.get("bytes") is not None:
            out.append({"type": "binary", "size": len(message["bytes"]), "head": message["bytes"][:4]})
        else:
            raise AssertionError(f"unexpected {message}")


def kinds(messages: list[dict]) -> list[str]:
    return [m["type"] for m in messages]


def hello(ws) -> dict:
    ws.send_text(json.dumps({"type": "hello"}))
    ready = collect(ws, "state")
    assert ready[0]["type"] == "ready"
    return ready[0]


def wait_for_llm(llm, calls: int = 1) -> None:
    """Interrupt only once the answer is being generated (the tests share one SQLite
    session, which mustn't be used by a cancelled database step and the next turn at once)."""
    import time

    deadline = time.monotonic() + 10
    while len(llm.calls) < calls:
        assert time.monotonic() < deadline, "the LLM was never called"
        time.sleep(0.02)


def row(db: Session, session: dict) -> RealtimeVoiceSession:
    db.expire_all()
    return db.get(RealtimeVoiceSession, uuid.UUID(session["session_id"]))


def finished_row(db: Session, session: dict) -> RealtimeVoiceSession:
    """The row once the server has finished the session (that runs just after the socket closes)."""
    import time

    deadline = time.monotonic() + 10
    while True:
        stored = row(db, session)
        if stored.status in ("ended", "failed", "expired") and manager.get(stored.id) is None:
            return stored
        assert time.monotonic() < deadline, f"session still {stored.status}"
        time.sleep(0.02)


# --- Settings ---------------------------------------------------------------------------


def test_settings_show_availability_and_capabilities(owner: TestClient):
    clone_id = new_clone(owner)
    body = owner.get(f"/api/clones/{clone_id}/realtime/settings").json()
    assert body["available"] is True and body["reason"] is None and body["provider"] == "pipeline"
    assert body["enabled"] is True and body["public_enabled"] is False and body["speech_mode"] == "voice"
    assert body["capabilities"]["transport"] == "websocket" and body["capabilities"]["interruption"] is True
    assert body["capabilities"]["languages"] == ["en", "ur", "roman-ur"]
    assert body["limits"]["max_duration_seconds"] == 600


def test_settings_need_login_and_owner_to_change(owner: TestClient, other: TestClient, client):
    clone_id = new_clone(owner)
    owner.patch(f"/api/clones/{clone_id}", json={"visibility": "public"})
    assert other.patch(f"/api/clones/{clone_id}/realtime/settings", json={"enabled": False}).status_code == 403
    updated = owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"speech_mode": "browser", "enabled": False})
    assert updated.status_code == 200 and updated.json()["speech_mode"] == "browser"
    assert updated.json()["available"] is False and updated.json()["reason"] == "realtime_off"
    assert owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"speech_mode": "loud"}).status_code == 400


def test_public_switch_needs_public_chat_and_voice(owner: TestClient):
    clone_id = new_clone(owner)
    refused = owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"public_enabled": True})
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_settings"
    open_to_public(owner, clone_id, voice=True)
    ok = owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"public_enabled": True})
    assert ok.status_code == 200 and ok.json()["public_enabled"] is True


def test_settings_report_why_unavailable(owner: TestClient, realtime_on, monkeypatch):
    clone_id = new_clone(owner, voice=False)
    assert owner.get(f"/api/clones/{clone_id}/realtime/settings").json()["reason"] == "consent_missing"
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", False)
    assert owner.get(f"/api/clones/{clone_id}/realtime/settings").json()["reason"] == "realtime_disabled"


# --- Session creation rules ---------------------------------------------------------------


def test_sessions_need_login(client: TestClient, owner: TestClient):
    clone_id = new_clone(owner)
    owner.post("/api/auth/logout")
    assert start(client, clone_id).status_code == 401


def test_feature_disabled_and_provider_not_configured(owner: TestClient, realtime_on, monkeypatch):
    clone_id = new_clone(owner)
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", False)
    off = start(owner, clone_id)
    assert off.status_code == 503 and off.json()["code"] == "realtime_disabled"
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", True)
    monkeypatch.setattr(realtime_on, "realtime_voice_provider", "made-up")
    assert start(owner, clone_id).json()["code"] == "provider_not_configured"
    monkeypatch.setattr(realtime_on, "realtime_voice_provider", "pipeline")
    from app.voice.base import VoiceNotConfiguredError

    def no_stt():
        raise VoiceNotConfiguredError("no key")

    monkeypatch.setattr("app.voice.factory.get_stt_provider", no_stt)
    unconfigured = start(owner, clone_id)
    assert unconfigured.status_code == 503 and unconfigured.json()["code"] == "provider_not_configured"


def test_consent_and_owner_switch(owner: TestClient):
    clone_id = new_clone(owner, voice=False)
    missing = start(owner, clone_id)
    assert missing.status_code == 409 and missing.json()["code"] == "consent_missing"
    enable_voice(owner, clone_id)
    owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"enabled": False})
    switched_off = start(owner, clone_id)
    assert switched_off.status_code == 409 and switched_off.json()["code"] == "realtime_off"


def test_other_users_and_disabled_clones(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner)
    assert start(other, clone_id).status_code == 404  # a private clone stays hidden
    owner.patch(f"/api/clones/{clone_id}", json={"status": "disabled"})
    assert start(owner, clone_id).status_code == 403


def test_session_is_created_with_a_hashed_one_time_ticket(owner: TestClient, db_session: Session, caplog):
    caplog.set_level(logging.DEBUG)
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    assert session["status"] == "created" and session["provider"] == "pipeline"
    assert session["ws_path"] == f"/api/realtime/sessions/{session['session_id']}/ws"
    assert session["ticket"].startswith("rt_") and len(session["ticket"]) > 30
    stored = row(db_session, session)
    assert stored.ticket_hash and session["ticket"] not in stored.ticket_hash
    status = owner.get(f"/api/clones/{clone_id}/realtime/session/{session['session_id']}")
    assert status.status_code == 200 and "ticket" not in status.text and session["ticket"] not in status.text
    assert session["ticket"] not in caplog.text


def test_sessions_are_private_to_their_user(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner)
    owner.patch(f"/api/clones/{clone_id}", json={"visibility": "public"})
    owner.patch(f"/api/clones/{clone_id}/public-settings", json={"public_chat_enabled": True})
    session = created(owner, clone_id)
    url = f"/api/clones/{clone_id}/realtime/session/{session['session_id']}"
    assert other.get(url).json()["code"] == "session_not_found"
    assert other.post(url + "/end").status_code == 404
    assert owner.get(f"/api/clones/{clone_id}/realtime/session/{uuid.uuid4()}").status_code == 404
    assert owner.get(f"/api/clones/{clone_id}/realtime/session/not-a-uuid").status_code == 400


def test_conversation_must_be_the_users_own(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner)
    conversation = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hi"}).json()["conversation_id"]
    assert created(owner, clone_id, conversation_id=conversation)["conversation_id"] == conversation
    assert start(owner, clone_id, conversation_id=str(uuid.uuid4())).status_code == 404


def test_rate_limit_and_concurrency(owner: TestClient, realtime_on, monkeypatch):
    clone_id = new_clone(owner)
    first = created(owner, clone_id)
    busy = start(owner, clone_id)
    assert busy.status_code == 409 and busy.json()["code"] == "too_many_sessions"
    owner.post(f"/api/clones/{clone_id}/realtime/session/{first['session_id']}/end")
    assert start(owner, clone_id).status_code == 201
    monkeypatch.setattr(realtime_on, "realtime_voice_max_concurrent_sessions", 10)
    monkeypatch.setattr(realtime_on, "realtime_voice_rate_limit_per_minute", 4)  # 3 starts so far
    assert start(owner, clone_id).status_code == 201
    limited = start(owner, clone_id)
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


def test_plan_quota(owner: TestClient, realtime_on, db_session: Session, monkeypatch):
    monkeypatch.setattr(realtime_on, "realtime_voice_max_concurrent_sessions", 10)
    clone_id = new_clone(owner)
    user = db_session.scalar(select(User).where(User.email == USER["email"].lower()))
    billing_service.seed_plans(db_session)
    subscription = billing_service.get_subscription(db_session, user.id)
    plan = billing_service.usage.get_plan(db_session, str(subscription.plan_id))
    plan.limits = {**(plan.limits or {}), "realtime_voice_sessions": 2}
    db_session.commit()
    assert start(owner, clone_id).status_code == 201
    assert start(owner, clone_id).status_code == 201
    over = start(owner, clone_id)
    assert over.status_code == 402 and over.json()["code"] == "quota_exceeded"


def test_unconnected_session_expires(owner: TestClient, db_session: Session, realtime_on, monkeypatch):
    clone_id = new_clone(owner)
    monkeypatch.setattr(realtime_on, "realtime_voice_session_ttl_seconds", 0)
    session = created(owner, clone_id)
    status = owner.get(f"/api/clones/{clone_id}/realtime/session/{session['session_id']}").json()
    assert status["status"] == "expired" and status["error_code"] == "session_expired"
    with pytest.raises(WebSocketDisconnect) as closed:
        with connect(owner, session) as ws:
            ws.receive_text()
    assert closed.value.code == 4404  # its ticket died with it
    # An expired session no longer counts against the concurrency limit.
    monkeypatch.setattr(realtime_on, "realtime_voice_session_ttl_seconds", 600)
    assert start(owner, clone_id).status_code == 201


def test_end_is_idempotent(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    url = f"/api/clones/{clone_id}/realtime/session/{session['session_id']}/end"
    assert owner.post(url).json()["status"] == "ended"
    assert owner.post(url).json()["status"] == "ended"
    assert manager.get(uuid.UUID(session["session_id"])) is None


# --- WebSocket -------------------------------------------------------------------------


def test_spoken_turn_end_to_end(owner: TestClient, stt, tts, llm, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        ready = hello(ws)
        assert ready["session_id"] == session["session_id"] and ready["speech_mode"] == "voice"
        ws.send_bytes(WAV)
        messages = collect(ws)
        ws.send_text(json.dumps({"type": "end"}))
        assert collect(ws, "ended")[-1]["reason"] == "client"
    types = kinds(messages)
    assert types[0] == "state" and messages[0]["state"] == "thinking"
    transcript = next(m for m in messages if m["type"] == "transcript")
    assert transcript["text"] == stt.text and transcript["turn"] == 1
    assert "answer_delta" in types and "answer" in types
    audio = types.index("audio")
    assert messages[audio]["mime"] in ("audio/mpeg", "audio/wav") and messages[audio + 1]["type"] == "binary"
    assert messages[audio + 1]["size"] > 100
    assert types[-1] == "turn_done"
    assert {"type": "state", "state": "speaking"} in messages
    answer = next(m for m in messages if m["type"] == "answer")
    # The turn is a normal chat turn: both messages saved, the answer spoken.
    saved = db_session.scalars(select(Message).order_by(Message.created_at)).all()
    assert [m.role for m in saved] == ["user", "assistant"] and saved[0].input_mode == "voice"
    assert saved[1].content == answer["text"] and answer["message_id"] == str(saved[1].id)
    assert tts.calls and llm.calls[-1]["message"] == stt.text
    stored = finished_row(db_session, session)
    assert stored.status == "ended" and stored.turns == 1 and stored.conversation_id == saved[0].conversation_id
    assert stored.duration_seconds is not None and stored.started_at is not None


def test_text_turn_and_browser_speech_mode(owner: TestClient, tts):
    clone_id = new_clone(owner)
    owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"speech_mode": "browser"})
    session = created(owner, clone_id)
    assert session["speech_mode"] == "browser"
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "Hello there"}))
        messages = collect(ws)
    assert "audio" not in kinds(messages) and "binary" not in kinds(messages) and "transcript" not in kinds(messages)
    assert "answer" in kinds(messages) and tts.calls == []


def test_speech_mode_can_change_during_the_call(owner: TestClient, tts):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "speech_mode", "mode": "browser"}))
        ws.send_text(json.dumps({"type": "text", "text": "Hello there"}))
        assert "audio" not in kinds(collect(ws))


def test_conversation_continues_across_turns(owner: TestClient, llm, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "First question"}))
        collect(ws, turn=1)
        ws.send_text(json.dumps({"type": "text", "text": "Second question"}))
        collect(ws, turn=2)
    assert [t["content"] for t in llm.calls[-1]["history"]][:1] == ["First question"]
    assert db_session.scalar(select(Conversation).where(Conversation.clone_id == uuid.UUID(clone_id))) is not None
    assert len(db_session.scalars(select(Conversation)).all()) == 1


def test_interrupt_cancels_the_answer(owner: TestClient, llm, tts, db_session: Session):
    clone_id = new_clone(owner)
    llm.delay = 5
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "Tell me a long story"}))
        assert collect(ws, "state")[-1]["state"] == "thinking"
        wait_for_llm(llm)
        ws.send_text(json.dumps({"type": "interrupt"}))
        messages = collect(ws, "interrupted")
        assert messages[-1]["turn"] == 1
        llm.delay = 0
        ws.send_text(json.dumps({"type": "text", "text": "Short one"}))
        second = collect(ws, turn=2)
    assert "turn_done" in kinds(second)
    assert not any(m["type"] == "answer" and m["turn"] == 1 for m in messages)
    # The cancelled answer produced no text, so only the second answer is saved.
    assert len(db_session.scalars(select(Message).where(Message.role == "assistant")).all()) == 1


def test_speaking_again_interrupts_the_running_turn(owner: TestClient, llm):
    clone_id = new_clone(owner)
    llm.delay = 5
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "First"}))
        collect(ws, "state")
        wait_for_llm(llm)
        llm.delay = 0
        ws.send_text(json.dumps({"type": "text", "text": "Actually, this"}))
        messages = collect(ws, turn=2)
    assert {"type": "interrupted", "turn": 1} in messages


def test_failures_are_safe_messages(owner: TestClient, llm, tts, stt, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        tts.error = VoiceUnavailableError("internal detail http://secret")
        ws.send_text(json.dumps({"type": "text", "text": "Hi"}))
        spoken = collect(ws)
        error = next(m for m in spoken if m["type"] == "error")
        assert error["code"] == "provider_unavailable" and error["fatal"] is False and "secret" not in json.dumps(error)
        assert "answer" in kinds(spoken)  # the text answer still arrives
        llm.error = LLMRateLimitError("quota detail")
        ws.send_text(json.dumps({"type": "text", "text": "Again"}))
        failed = collect(ws, "error")
        assert failed[-1]["code"] == "provider_unavailable" and "quota detail" not in json.dumps(failed)
        ws.send_bytes(b"not audio at all")
        bad_audio = collect(ws, "error")
        assert bad_audio[-1]["code"] == "invalid_audio"
    events = db_session.scalars(select(AnalyticsEvent).where(AnalyticsEvent.event_type == "realtime_voice_provider_error")).all()
    assert events and all("quota" not in json.dumps(e.metadata) for e in events)


def test_bad_messages(owner: TestClient, realtime_on, monkeypatch):
    clone_id = new_clone(owner)
    monkeypatch.setattr(realtime_on, "realtime_voice_max_utterance_bytes", 1000)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_bytes(b"x" * 2000)
        assert collect(ws, "error")[-1]["code"] == "invalid_audio"
        ws.send_text(json.dumps({"type": "text", "text": "   "}))
        assert collect(ws, "error")[-1]["code"] == "invalid_message"
        ws.send_text(json.dumps({"type": "ping"}))
        assert collect(ws, "pong")
        ws.send_text("{not json")
        assert collect(ws, "error")[-1]["fatal"] is True
        closed = ws.receive()
        assert closed["type"] == "websocket.close" and closed["code"] == 4400


def test_ticket_is_single_use_and_checked(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with pytest.raises(WebSocketDisconnect) as wrong:
        with connect(owner, session, ticket="rt_" + "x" * 40) as ws:
            ws.receive_text()
    assert wrong.value.code == 4403
    with connect(owner, session) as ws:
        hello(ws)
    with pytest.raises(WebSocketDisconnect) as reused:
        with connect(owner, session) as ws:
            ws.receive_text()
    assert reused.value.code in (4403, 4404)
    failed = db_session.scalars(
        select(AnalyticsEvent).where(AnalyticsEvent.event_type == "realtime_voice_connection_failed")
    ).all()
    assert failed and session["ticket"] not in json.dumps([e.metadata for e in failed])


def test_origin_is_checked(owner: TestClient):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    for origin in ("https://evil.example", None):
        with pytest.raises(WebSocketDisconnect) as refused:
            with connect(owner, session, origin=origin) as ws:
                ws.receive_text()
        assert refused.value.code == 4403
    with connect(owner, session) as ws:  # the ticket wasn't spent by refused origins
        hello(ws)


def test_max_duration_ends_the_session(owner: TestClient, realtime_on, monkeypatch, db_session: Session):
    clone_id = new_clone(owner)
    monkeypatch.setattr(realtime_on, "realtime_voice_max_duration_seconds", 1)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ended = collect(ws, "ended")
    assert ended[-1]["reason"] == "max_duration"
    assert finished_row(db_session, session).status == "ended"


def test_disconnect_cleans_up_and_records_usage(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "Hi"}))
        collect(ws)
    stored = finished_row(db_session, session)
    assert stored.status == "ended" and stored.turns == 1
    assert manager.get(uuid.UUID(session["session_id"])) is None
    types = {e.event_type for e in db_session.scalars(select(AnalyticsEvent)).all()}
    assert {"realtime_voice_session_started", "realtime_voice_session_ended"} <= types
    usage = db_session.scalars(select(UsageEvent).where(UsageEvent.event_type == "REALTIME_VOICE_SESSION")).all()
    assert len(usage) == 1 and usage[0].status == "success"
    # A new session can start once the old one is gone.
    assert start(owner, clone_id).status_code == 201


def test_ending_through_the_api_closes_the_socket(owner: TestClient):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        assert owner.post(f"/api/clones/{clone_id}/realtime/session/{session['session_id']}/end").json()["status"] == "ended"
        assert collect(ws, "ended")[-1]["reason"] == "client"


def test_access_is_rechecked_every_turn(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    session = created(owner, clone_id)
    with connect(owner, session) as ws:
        hello(ws)
        owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_enabled": False})
        ws.send_bytes(WAV)
        assert collect(ws, "error")[-1]["code"] == "forbidden"


# --- Public visitors ---------------------------------------------------------------------


PUBLIC_FACT = "I build Django and FastAPI apps."
PRIVATE_FACT = "My home is on Secret Street."


@pytest.fixture
def visitor(make_client) -> TestClient:
    return make_client()


def published(owner: TestClient, *, realtime: bool = True) -> dict:
    clone_id = new_clone(owner)
    add_document(owner, clone_id, PUBLIC_FACT, "Work", public=True)
    add_document(owner, clone_id, PRIVATE_FACT, "Private notes", public=False)
    add_memory(owner, clone_id, "I mentor juniors on Fridays.", public=False)
    open_to_public(owner, clone_id, voice=True)
    if realtime:
        assert owner.patch(f"/api/clones/{clone_id}/realtime/settings", json={"public_enabled": True}).status_code == 200
    return owner.get(f"/api/clones/{clone_id}").json()


def public_token(visitor: TestClient, slug: str) -> str:
    response = visitor.post(f"/api/public/clones/{slug}/chat", json={"message": "hello"})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_public_realtime_is_off_by_default(owner: TestClient, visitor: TestClient):
    clone = published(owner, realtime=False)
    token = public_token(visitor, clone["slug"])
    response = visitor.post(f"/api/public/clones/{clone['slug']}/realtime/session", headers={"X-Public-Session": token})
    assert response.status_code == 409 and response.json()["code"] == "realtime_off"


def test_public_session_needs_a_public_chat_token(owner: TestClient, visitor: TestClient):
    clone = published(owner)
    assert visitor.post(f"/api/public/clones/{clone['slug']}/realtime/session").status_code in (401, 403, 404)
    bad = visitor.post(f"/api/public/clones/{clone['slug']}/realtime/session", headers={"X-Public-Session": "nope"})
    assert bad.status_code in (401, 403, 404)


def test_public_turn_uses_public_knowledge_only(owner: TestClient, visitor: TestClient, llm, db_session: Session, monkeypatch):
    clone = published(owner)
    token = public_token(visitor, clone["slug"])
    used: list[str] = []
    real_public = pipeline.public_rag_pipeline.retrieve_public_context

    def spy(db, clone_row, question):
        used.append("public")
        return real_public(db, clone_row, question)

    monkeypatch.setattr(pipeline.public_rag_pipeline, "retrieve_public_context", spy)
    response = visitor.post(f"/api/public/clones/{clone['slug']}/realtime/session", headers={"X-Public-Session": token})
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["conversation_id"] is None
    with connect(visitor, session) as ws:
        hello(ws)
        ws.send_text(json.dumps({"type": "text", "text": "Tell me about Django apps home street mentor"}))
        messages = collect(ws)
    assert "answer" in kinds(messages) and used == ["public"]
    sent = everything_sent(llm)
    assert "Django and FastAPI" in sent and "Secret Street" not in sent and "mentor juniors" not in sent
    stored = row(db_session, session)
    assert stored.is_public and stored.owner_id is None and stored.visitor_key


def test_public_session_is_ended_only_by_its_visitor(owner: TestClient, visitor: TestClient, make_client):
    clone = published(owner)
    token = public_token(visitor, clone["slug"])
    session = visitor.post(
        f"/api/public/clones/{clone['slug']}/realtime/session", headers={"X-Public-Session": token}
    ).json()
    stranger = make_client()
    other_token = public_token(stranger, clone["slug"])
    url = f"/api/public/clones/{clone['slug']}/realtime/session/{session['session_id']}/end"
    assert stranger.post(url, headers={"X-Public-Session": other_token}).status_code == 404
    assert visitor.post(url, headers={"X-Public-Session": token}).json()["status"] == "ended"


def test_public_switch_off_stops_new_turns(owner: TestClient, visitor: TestClient):
    clone = published(owner)
    token = public_token(visitor, clone["slug"])
    session = visitor.post(
        f"/api/public/clones/{clone['slug']}/realtime/session", headers={"X-Public-Session": token}
    ).json()
    with connect(visitor, session) as ws:
        hello(ws)
        owner.patch(f"/api/clones/{clone['id']}/realtime/settings", json={"public_enabled": False})
        ws.send_text(json.dumps({"type": "text", "text": "Hi"}))
        assert collect(ws, "error")[-1]["code"] == "realtime_off"


# --- Configuration exposure and regressions ---------------------------------------------------


def test_mobile_config_reports_realtime_voice(client: TestClient, realtime_on, monkeypatch):
    assert client.get("/api/mobile/config").json()["voice"]["realtime_voice"] is True
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", False)
    assert client.get("/api/mobile/config").json()["voice"]["realtime_voice"] is False


def test_text_and_voice_chat_still_work(owner: TestClient):
    clone_id = new_clone(owner)
    stream = owner.post(f"/api/clones/{clone_id}/chat/stream", json={"message": "Hello"})
    assert stream.status_code == 200 and "event: done" in stream.text
    voice = owner.post(f"/api/clones/{clone_id}/voice/chat", files={"audio": ("v.wav", WAV, "audio/wav")})
    assert voice.status_code == 200, voice.text


def test_sentences_are_split_for_speech():
    done, rest = pipeline.take_sentences("Hello there. How are", final=False)
    assert done == ["Hello there."] and rest == "How are"
    done, rest = pipeline.take_sentences("آپ کیسے ہیں؟ ٹھیک", final=True)
    assert done == ["آپ کیسے ہیں؟", "ٹھیک"] and rest == ""
    long = "word " * 100
    done, rest = pipeline.take_sentences(long, final=False)
    assert all(len(piece) <= pipeline.MAX_SENTENCE_CHARACTERS for piece in done) and len(rest) <= 300


def test_clone_profile_defaults(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    clone = db_session.get(CloneProfile, uuid.UUID(clone_id))
    assert clone.realtime_voice_enabled is True and clone.public_realtime_voice_enabled is False
    assert clone.realtime_speech_mode == "voice"


def test_public_profile_reports_realtime_voice(owner: TestClient, visitor: TestClient, realtime_on, monkeypatch):
    clone = published(owner, realtime=False)
    url = f"/api/public/clones/{clone['slug']}"
    assert visitor.get(url).json()["realtime_voice_available"] is False
    owner.patch(f"/api/clones/{clone['id']}/realtime/settings", json={"public_enabled": True})
    assert visitor.get(url).json()["realtime_voice_available"] is True
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", False)
    assert visitor.get(url).json()["realtime_voice_available"] is False
    monkeypatch.setattr(realtime_on, "realtime_voice_enabled", True)
    owner.patch(f"/api/clones/{clone['id']}/public-settings", json={"public_voice_enabled": False})
    assert visitor.get(url).json()["realtime_voice_available"] is False


def test_tickets_are_redacted_from_server_logs():
    import logging

    from app.realtime_voice.safety import RedactTicketFilter

    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, '%s - "WebSocket %s" %d',
        ("127.0.0.1:5000", "/api/realtime/sessions/abc/ws?ticket=rt_secretvalue123&x=1", 403), None,
    )
    assert RedactTicketFilter().filter(record) is True
    assert "rt_secretvalue123" not in record.getMessage()
    assert "ticket=***&x=1" in record.getMessage()
    assert any(isinstance(f, RedactTicketFilter) for f in logging.getLogger("uvicorn.error").filters)
