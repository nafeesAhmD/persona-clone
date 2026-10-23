"""Phase 7: voice (speech-to-text, voice chat on the text pipeline, text-to-speech).

STT and TTS are tests/conftest.FakeSTT / FakeTTS; the audio itself is real
(WAV, WebM/Opus and MP3 made with PyAV), so validation and encoding run for real.
"""

import io
import os
import time
import uuid

import av
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import LLMRateLimitError
from app.models import CloneProfile, Message
from app.services.qdrant_service import LongTermMemoryStore, QdrantService, VectorStoreError
from app.voice.audio import encode_mp3, sniff_format
from app.voice.base import VoiceNotConfiguredError, VoiceUnavailableError
from app.voice.storage import get_voice_store
from app.voice.text_to_speech import speakable
from tests.conftest import USER, open_to_public, tone_wav

CLONE = {"name": "Ayaan AI", "profession": "Software Developer", "owner_consent": True}
WAV = tone_wav(1.0)


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


def new_clone(client: TestClient, *, voice: bool = True, **overrides) -> str:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    if voice:
        enable_voice(client, clone_id)
    return clone_id


def enable_voice(client: TestClient, clone_id: str) -> dict:
    response = client.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
    )
    assert response.status_code == 200, response.text
    return response.json()


def transcribe(client: TestClient, clone_id: str, data: bytes = WAV, name: str = "voice.wav", mime: str = "audio/wav"):
    return client.post(f"/api/clones/{clone_id}/voice/transcribe", files={"audio": (name, data, mime)})


def voice_chat(client: TestClient, clone_id: str, conversation_id: str | None = None, data: bytes = WAV):
    form = {"conversation_id": conversation_id} if conversation_id else {}
    return client.post(
        f"/api/clones/{clone_id}/voice/chat", files={"audio": ("voice.wav", data, "audio/wav")}, data=form
    )


def teach(client: TestClient, clone_id: str, content: str) -> None:
    response = client.post(f"/api/clones/{clone_id}/knowledge", json={"title": "My CV", "content": content})
    assert response.status_code == 201 and response.json()["indexing_status"] == "indexed"


def transcode(data: bytes, fmt: str, codec: str, rate: int) -> bytes:
    out = io.BytesIO()
    with av.open(io.BytesIO(data)) as source, av.open(out, "w", format=fmt) as target:
        stream = target.add_stream(codec, rate=rate)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format.name, layout="mono", rate=rate)
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                for packet in stream.encode(converted):
                    target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    return out.getvalue()


# --- Speech-to-text -------------------------------------------------------------------


def test_transcribe_wav(owner: TestClient, stt):
    clone_id = new_clone(owner)
    response = transcribe(owner, clone_id)
    assert response.status_code == 200, response.text
    assert response.json() == {"text": stt.text, "language": "en", "duration_seconds": 1.0}
    assert stt.calls[0]["wav"] == b"RIFF"  # the provider gets our normalised WAV, not the upload


@pytest.mark.parametrize(
    ("fmt", "codec", "name", "mime"),
    [
        ("webm", "libopus", "voice.webm", "audio/webm;codecs=opus"),
        ("mp3", "libmp3lame", "voice.mp3", "audio/mpeg"),
        ("ogg", "libopus", "voice.ogg", "audio/ogg"),
    ],
)
def test_transcribe_browser_formats(owner: TestClient, stt, fmt, codec, name, mime):
    clone_id = new_clone(owner)
    data = transcode(tone_wav(2.0), fmt, codec, 48_000 if codec == "libopus" else 24_000)
    response = transcribe(owner, clone_id, data, name, mime)
    assert response.status_code == 200, response.text
    assert 1.8 <= response.json()["duration_seconds"] <= 2.2


@pytest.mark.parametrize(
    ("data", "name", "mime", "status"),
    [
        (b"hello, I am not audio", "voice.wav", "audio/wav", 415),  # bytes aren't WAV
        (WAV, "voice.exe", "audio/wav", 415),  # extension not allowed
        (WAV, "voice.wav", "text/plain", 415),  # MIME not allowed
        (WAV, "voice.mp3", "audio/mpeg", 415),  # name and type say MP3, bytes are WAV
        (b"RIFF\x00\x00\x00\x00WAVEgarbage-garbage", "voice.wav", "audio/wav", 400),  # looks like WAV, isn't
        (b"", "voice.wav", "audio/wav", 400),
    ],
    # Explicit short ids: raw WAV bytes would otherwise become a multi-kilobyte
    # test id, which overflows the process environment block on Windows.
    ids=["not-audio", "bad-extension", "bad-mime", "mismatched-mp3", "malformed-wav", "empty"],
)
def test_invalid_audio_is_rejected(owner: TestClient, stt, data, name, mime, status):
    clone_id = new_clone(owner)
    response = transcribe(owner, clone_id, data, name, mime)
    assert response.status_code == status, response.text
    assert stt.calls == []


def test_oversized_audio_is_rejected(owner: TestClient, stt, monkeypatch):
    from app.core.config import get_settings

    clone_id = new_clone(owner)
    monkeypatch.setattr(get_settings(), "max_audio_size_mb", 1)
    big = tone_wav(40.0)  # ~1.3 MB
    response = transcribe(owner, clone_id, big)
    assert response.status_code == 413
    assert "Maximum size is 1 MB" in response.json()["detail"]
    assert stt.calls == []


def test_too_long_and_too_short_recordings(owner: TestClient, stt, monkeypatch):
    from app.core.config import get_settings

    clone_id = new_clone(owner)
    monkeypatch.setattr(get_settings(), "max_audio_duration_seconds", 1.5)
    assert transcribe(owner, clone_id, tone_wav(2.0)).status_code == 413
    assert transcribe(owner, clone_id, tone_wav(0.1)).status_code == 400
    assert stt.calls == []


def test_transcribe_access_rules(owner: TestClient, other: TestClient, make_client, db_session: Session):
    private = new_clone(owner)
    assert make_client().post(
        f"/api/clones/{private}/voice/transcribe", files={"audio": ("v.wav", WAV, "audio/wav")}
    ).status_code == 401
    assert transcribe(other, private).status_code == 404
    assert transcribe(owner, str(uuid.uuid4())).status_code == 404
    silent = new_clone(owner, voice=False)
    response = transcribe(owner, silent)
    assert response.status_code == 403 and response.json()["detail"] == "Voice is turned off for this AI Clone."
    owner.patch(f"/api/clones/{private}", json={"status": "disabled"})
    assert transcribe(owner, private).json()["detail"] == "This AI Clone is currently disabled."


def test_stt_failures_are_friendly(owner: TestClient, stt):
    clone_id = new_clone(owner)
    stt.text = "   "
    assert transcribe(owner, clone_id).status_code == 422
    stt.error = VoiceUnavailableError("upstream 500 with secret detail")
    response = transcribe(owner, clone_id)
    assert response.status_code == 503 and "secret" not in response.text


def test_urdu_speech_is_kept_as_spoken(owner: TestClient, stt, llm):
    clone_id = new_clone(owner, preferred_language="Roman Urdu")
    stt.text, stt.language = "آپ مجھے Python سکھا سکتے ہیں؟", "hi"
    response = voice_chat(owner, clone_id)
    assert response.status_code == 200
    assert response.json()["transcript"] == stt.text
    assert response.json()["language"] == "ur"
    assert llm.calls[-1]["message"] == stt.text  # not translated
    assert stt.calls[-1]["hint"] == "Roman Urdu"


def test_voice_rate_limit(owner: TestClient, monkeypatch):
    from app.core.config import get_settings

    clone_id = new_clone(owner)
    monkeypatch.setattr(get_settings(), "voice_rate_limit_per_minute", 2)
    assert transcribe(owner, clone_id).status_code == 200
    assert transcribe(owner, clone_id).status_code == 200
    response = transcribe(owner, clone_id)
    assert response.status_code == 429 and "voice requests" in response.json()["detail"]


# --- Voice chat -----------------------------------------------------------------------


def test_voice_chat_runs_the_normal_chat_pipeline(owner: TestClient, stt, tts, llm, db_session: Session):
    clone_id = new_clone(owner)
    teach(owner, clone_id, "I have worked with Python, Django and FastAPI.")
    owner.post(f"/api/clones/{clone_id}/memories", json={"memory_type": "skill", "content": "The user worked with FastAPI technologies."})

    response = voice_chat(owner, clone_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == stt.text
    assert "Django" in body["answer"] and "FastAPI" in body["answer"]  # knowledge RAG
    assert body["memories_used"] == 1  # long-term memory
    assert [s["title"] for s in body["sources"]] == ["My CV"]
    assert body["tts_error"] is None and body["audio_url"].startswith("/api/voice/audio/")
    assert tts.calls[-1]["text"] == body["answer"]

    stored = list(db_session.scalars(select(Message).order_by(Message.created_at)))
    assert [(m.role, m.content) for m in stored] == [("user", stt.text), ("assistant", body["answer"])]
    assert str(stored[0].conversation_id) == body["conversation_id"]

    audio = owner.get(body["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    assert sniff_format(audio.content) == "mp3"


def test_spoken_messages_are_marked_as_voice(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    voice = voice_chat(owner, clone_id).json()
    assert voice["message"]["input_mode"] == "text"  # the clone's answer
    conversation_id = voice["conversation_id"]
    streamed = owner.post(
        f"/api/clones/{clone_id}/chat/stream",
        json={"message": "What next?", "conversation_id": conversation_id, "input_mode": "voice"},
    )
    assert streamed.status_code == 200
    owner.post(f"/api/clones/{clone_id}/chat", json={"message": "typed", "conversation_id": conversation_id})

    messages = owner.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert [(m["role"], m["input_mode"]) for m in messages] == [
        ("user", "voice"), ("assistant", "text"), ("user", "voice"), ("assistant", "text"), ("user", "text"), ("assistant", "text"),
    ]
    bad = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hi", "conversation_id": None, "input_mode": "video"})
    assert bad.status_code == 400


def test_voice_conversation_continues(owner: TestClient, stt, llm):
    clone_id = new_clone(owner)
    first = voice_chat(owner, clone_id).json()
    stt.text = "And which one do you like most?"
    second = voice_chat(owner, clone_id, first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert [turn["role"] for turn in llm.calls[-1]["history"]] == ["user", "assistant"]
    conversation = owner.get(f"/api/conversations/{first['conversation_id']}").json()
    assert len(conversation["messages"]) == 4
    assert voice_chat(owner, clone_id, "not-a-uuid").status_code == 400


def test_tts_failure_still_returns_the_text_answer(owner: TestClient, tts, db_session: Session):
    clone_id = new_clone(owner)
    tts.error = VoiceUnavailableError("tts down")
    response = voice_chat(owner, clone_id)
    assert response.status_code == 200
    body = response.json()
    assert body["audio_url"] is None
    assert body["tts_error"] == "Voice generation temporarily unavailable"
    assert body["answer"]
    assert len(db_session.scalars(select(Message)).all()) == 2


def test_memory_search_failure_does_not_break_voice_chat(owner: TestClient, monkeypatch):
    clone_id = new_clone(owner)
    teach(owner, clone_id, "I have worked with Python, Django and FastAPI.")

    def down(self, **kwargs):
        raise VectorStoreError("down")

    monkeypatch.setattr(LongTermMemoryStore, "search", down)
    response = voice_chat(owner, clone_id)
    assert response.status_code == 200 and "Django" in response.json()["answer"]


def test_knowledge_search_failure_fails_like_text_chat(owner: TestClient, monkeypatch, tts):
    clone_id = new_clone(owner)

    def down(self, **kwargs):
        raise VectorStoreError("The memory store (Qdrant) is not available")

    monkeypatch.setattr(QdrantService, "search_similar_chunks", down)
    response = voice_chat(owner, clone_id)
    assert response.status_code == 503
    assert tts.calls == []


def test_llm_failure_is_friendly_and_saves_no_reply(owner: TestClient, llm, tts, db_session: Session):
    clone_id = new_clone(owner)
    llm.error = LLMRateLimitError("quota detail")
    response = voice_chat(owner, clone_id)
    assert response.status_code == 429 and "quota detail" not in response.text
    assert [m.role for m in db_session.scalars(select(Message))] == ["user"]
    assert tts.calls == []


def test_visitors_can_voice_chat_with_a_public_clone_without_owner_memories(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner, visibility="public")
    open_to_public(owner, clone_id, voice=True)
    owner.post(f"/api/clones/{clone_id}/memories", json={"memory_type": "skill", "content": "The user worked with FastAPI technologies."})
    response = voice_chat(other, clone_id)
    assert response.status_code == 200 and response.json()["memories_used"] == 0
    # The owner can't see the visitor's conversation or audio.
    assert owner.get(f"/api/conversations/{response.json()['conversation_id']}").status_code == 404
    assert owner.get(response.json()["audio_url"]).status_code == 404


def test_turning_voice_off_blocks_voice_but_not_text_chat(owner: TestClient):
    clone_id = new_clone(owner)
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_enabled": False})
    assert voice_chat(owner, clone_id).status_code == 403
    text = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hello", "conversation_id": None})
    assert text.status_code == 200
    assert owner.get(f"/api/clones/{clone_id}/chat-profile").json()["voice_enabled"] is False


def test_speaking_a_saved_answer(owner: TestClient, other: TestClient, tts):
    clone_id = new_clone(owner, visibility="public")
    chat = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hello", "conversation_id": None}).json()
    conversation_id, answer_id = chat["conversation_id"], chat["message"]["id"]
    question_id = owner.get(f"/api/conversations/{conversation_id}").json()["messages"][0]["id"]
    speech = f"/api/conversations/{conversation_id}/messages"

    response = owner.post(f"{speech}/{answer_id}/speech")
    assert response.status_code == 200
    assert tts.calls[-1]["text"] == chat["message"]["content"]
    assert owner.get(response.json()["audio_url"]).status_code == 200
    assert owner.post(f"{speech}/{question_id}/speech").status_code == 404  # only the clone's answers
    assert owner.post(f"{speech}/{uuid.uuid4()}/speech").status_code == 404
    assert other.post(f"{speech}/{answer_id}/speech").status_code == 404  # someone else's conversation
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_enabled": False})
    assert owner.post(f"{speech}/{answer_id}/speech").status_code == 403


# --- Text-to-speech, settings and consent --------------------------------------------


def test_voice_test_generates_audio(owner: TestClient, tts):
    clone_id = new_clone(owner)
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_id": "bass", "voice_language": "ur"})
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hello, this is my AI Clone."})
    assert response.status_code == 200
    assert tts.calls[-1] == {"text": "Hello, this is my AI Clone.", "voice": "bass", "language": "ur"}
    assert owner.get(response.json()["audio_url"]).status_code == 200


def test_voice_test_rules(owner: TestClient, other: TestClient, tts):
    clone_id = new_clone(owner, visibility="public")
    assert other.post(f"/api/clones/{clone_id}/voice/test", json={}).status_code == 403
    silent = new_clone(owner, voice=False)
    assert owner.post(f"/api/clones/{silent}/voice/test", json={}).status_code == 403
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "  "}).status_code == 400
    tts.error = VoiceUnavailableError("down")
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={})
    assert response.status_code == 503 and response.json()["detail"].startswith("The voice service")


def test_missing_voice_configuration(owner: TestClient, monkeypatch):
    clone_id = new_clone(owner, voice=False)

    def not_configured():
        raise VoiceNotConfiguredError("no key")

    monkeypatch.setattr("app.voice.factory.get_tts_provider", not_configured)
    settings = owner.get(f"/api/clones/{clone_id}/voice/settings").json()
    assert settings["tts_provider"] is None and settings["voices"] == []
    response = owner.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Voice is not available on this server right now."


def test_voice_cannot_be_enabled_without_consent(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner, voice=False)
    response = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_enabled": True})
    assert response.status_code == 403
    assert response.json()["detail"] == "Voice consent is required before voice can be turned on."
    db_session.expire_all()
    assert db_session.get(CloneProfile, uuid.UUID(clone_id)).voice_enabled is False


def test_consent_lifecycle(owner: TestClient):
    clone_id = new_clone(owner, voice=False)
    settings = owner.get(f"/api/clones/{clone_id}/voice/settings").json()
    assert settings["voice_enabled"] is False and settings["voice_consent_given"] is False
    assert settings["voice_type"] == "ai_generated"

    enabled = enable_voice(owner, clone_id)
    assert enabled["voice_enabled"] is True and enabled["voice_consent_at"] is not None
    assert enabled["voice_provider"] == "fake-tts" and enabled["voice_id"] == "alto"  # defaults

    withdrawn = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": False}).json()
    assert withdrawn["voice_enabled"] is False and withdrawn["voice_consent_at"] is None


def test_custom_voice_needs_consent(owner: TestClient):
    clone_id = new_clone(owner, voice=False)
    response = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_id": "custom-owner"})
    assert response.status_code == 403
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True})
    chosen = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_id": "custom-owner"}).json()
    assert chosen["voice_type"] == "custom"


def test_settings_validation_and_ownership(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner, visibility="public")
    base = f"/api/clones/{clone_id}/voice/settings"
    assert owner.patch(base, json={"voice_id": "nobody"}).status_code == 400
    assert owner.patch(base, json={"voice_provider": "elsewhere"}).status_code == 400
    assert owner.patch(base, json={"voice_language": "fr"}).status_code == 400
    assert owner.patch(base, json={"voice_consent_at": "2020-01-01"}).status_code == 400  # server-set
    assert other.get(base).status_code == 403
    assert other.patch(base, json={"voice_enabled": False}).status_code == 403
    private = new_clone(owner)
    assert other.get(f"/api/clones/{private}/voice/settings").status_code == 404


# --- Audio files ----------------------------------------------------------------------


def test_generated_audio_is_private_and_paths_are_safe(owner: TestClient, other: TestClient):
    clone_id = new_clone(owner)
    url = owner.post(f"/api/clones/{clone_id}/voice/test", json={}).json()["audio_url"]
    assert other.get(url).status_code == 404
    assert owner.get("/api/voice/audio/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert owner.get("/api/voice/audio/" + "g" * 32).status_code == 404
    assert owner.get(f"/api/voice/audio/{uuid.uuid4().hex}").status_code == 404


def test_expired_audio_is_cleaned_up_but_knowledge_files_stay(owner: TestClient, storage_dir):
    clone_id = new_clone(owner)
    owner.post(f"/api/clones/{clone_id}/documents", files={"file": ("cv.txt", b"I work with Python and Django every day.", "text/plain")})
    url = owner.post(f"/api/clones/{clone_id}/voice/test", json={}).json()["audio_url"]
    audio_files = list((storage_dir / "voice").rglob("*.mp3"))
    assert len(audio_files) == 1
    old = time.time() - 25 * 3600
    os.utime(audio_files[0], (old, old))

    assert owner.get(url).status_code == 404  # expired even before cleanup runs
    assert get_voice_store().cleanup() == 1
    assert list((storage_dir / "voice").rglob("*.mp3")) == []
    assert len(list((storage_dir / "clones").rglob("*.txt"))) == 1


def test_speakable_text():
    assert speakable("**Hello** there!\n- one\n- two\n```py\nprint(1)\n```\n[docs](http://x)") == "Hello there! one two docs"
    assert speakable("First sentence. Second sentence is long.", max_characters=20) == "First sentence."


def test_mp3_encoding():
    mp3 = encode_mp3(tone_wav(0.5, 24_000))
    assert sniff_format(mp3) == "mp3"
    with av.open(io.BytesIO(mp3)) as container:
        assert container.streams.audio[0].rate == 24_000


# --- Staying available on free-tier quotas --------------------------------------------


def test_tts_uses_the_next_model_and_skips_exhausted_ones_for_a_while():
    import asyncio
    from types import SimpleNamespace

    from google.genai import errors

    from app.core.config import get_settings
    from app.voice.providers import gemini

    gemini.reset_cooldowns()
    settings = get_settings().model_copy(
        update={"gemini_api_key": "k", "tts_model": "main-tts", "tts_fallback_models": "second-tts, third-tts,main-tts"}
    )
    provider = gemini.GeminiTextToSpeech(settings)
    assert provider.models == ["main-tts", "second-tts", "third-tts"]
    used: list[str] = []

    async def generate_content(model, contents, config):
        used.append(model)
        if model != "third-tts":
            message = "Quota exceeded for GenerateRequestsPerDayPerProjectPerModel-FreeTier"
            raise errors.ClientError(429, {"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}})
        blob = SimpleNamespace(data=tone_wav(0.2, 24_000), mime_type="audio/wav")
        part = SimpleNamespace(inline_data=blob)
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    provider._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    assert asyncio.run(provider.synthesize("hi", "Kore")).data[:4] == b"RIFF"
    assert used == ["main-tts", "second-tts", "third-tts"]
    used.clear()
    asyncio.run(provider.synthesize("again", "Kore"))
    assert used == ["third-tts"]  # the exhausted models are skipped, no time wasted
    gemini.reset_cooldowns()


def test_all_tts_models_exhausted_is_a_clear_429(owner: TestClient, tts):
    from app.voice.base import VoiceRateLimitError

    clone_id = new_clone(owner)
    tts.error = VoiceRateLimitError("all quotas used")
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={})
    assert response.status_code == 429
    assert "free usage limit" in response.json()["detail"]


def test_speech_for_an_answer_is_generated_once_and_reused(owner: TestClient, tts):
    clone_id = new_clone(owner)
    chat = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hello", "conversation_id": None}).json()
    url = f"/api/conversations/{chat['conversation_id']}/messages/{chat['message']['id']}/speech"
    first = owner.post(url).json()["audio_url"]
    second = owner.post(url).json()["audio_url"]
    assert first == second
    assert len(tts.calls) == 1  # the second "Play" costs no provider request
    assert owner.get(second).status_code == 200
