"""Two voice-clone services: a GPU one (e.g. Colab) first, the laptop one as fallback."""

import asyncio
import json

import httpx
import pytest

from app.core.config import get_settings
from app.voice import pronounce
from app.voice.base import InvalidAudioError, VoiceUnavailableError
from app.voice.providers import local_clone
from app.voice.providers.elevenlabs import VoiceNotFoundError
from tests.test_voice_clone_local import SPEECH_WAV

GPU = "https://gpu.example.trycloudflare.com"
LAPTOP = "http://voice-clone:8100"
VOICE = "0123456789abcdef0123456789abcdef"


class FakeServices:
    """Answers for both hosts. `down` = hosts that fail with 530 (a closed Colab tunnel)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.down: set[str] = set()
        self.connect_timeout: set[str] = set()  # hosts that never answer the connection
        self.engine = {"gpu.example.trycloudflare.com": "omnivoice", "voice-clone": "chatterbox"}
        self.missing_voice: set[str] = set()
        self.bad_audio = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.requests.append(request)
        if host in self.connect_timeout:
            raise httpx.ConnectTimeout("no route", request=request)
        if host in self.down:
            return httpx.Response(530)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "model_loaded": True, "engine": self.engine[host]})
        if request.method == "POST" and path == "/voices":
            if self.bad_audio:
                return httpx.Response(400, json={"detail": "not enough speech"})
            chosen = request.content.split(b'name="voice_id"\r\n\r\n')[1][:32].decode()
            return httpx.Response(201, json={"voice_id": chosen, "reference_seconds": 12.0})
        if request.method == "POST" and path == "/synthesize":
            if host in self.missing_voice:
                return httpx.Response(404, json={"detail": "voice not found"})
            return httpx.Response(200, content=SPEECH_WAV, headers={"content-type": "audio/wav"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    def made(self, host: str, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host and r.method == method and r.url.path == path]


@pytest.fixture
def services(monkeypatch) -> FakeServices:
    fake = FakeServices()
    settings = get_settings()
    monkeypatch.setattr(settings, "local_voice_clone_url", GPU)
    monkeypatch.setattr(settings, "local_voice_clone_fallback_url", LAPTOP)
    monkeypatch.setattr(settings, "voice_clone_service_token", "t" * 32)
    monkeypatch.setattr(settings, "voice_llm_transliteration", False)
    monkeypatch.setattr(local_clone, "_transport", httpx.MockTransport(fake.handle))
    local_clone.reset_engine_cache()
    pronounce.clear_cache()
    yield fake
    local_clone.reset_engine_cache()


def run(coro):
    return asyncio.run(coro)


def sent(fake: FakeServices, host: str) -> list[dict]:
    return [json.loads(r.content) for r in fake.made(host, "POST", "/synthesize")]


def test_a_new_voice_is_stored_on_both_services_under_one_id(services):
    voice = run(local_clone.LocalVoiceClone().clone_voice("me", [("a.wav", b"RIFF", "audio/wav")]))
    assert len(services.made("gpu.example.trycloudflare.com", "POST", "/voices")) == 1
    assert len(services.made("voice-clone", "POST", "/voices")) == 1
    for request in [r for r in services.requests if r.method == "POST"]:
        assert f'name="voice_id"\r\n\r\n{voice}'.encode() in request.content


def test_voice_is_stored_on_the_laptop_when_the_gpu_is_off(services):
    services.down.add("gpu.example.trycloudflare.com")
    voice = run(local_clone.LocalVoiceClone().clone_voice("me", [("a.wav", b"RIFF", "audio/wav")]))
    assert len(voice) == 32 and len(services.made("voice-clone", "POST", "/voices")) == 1


def test_bad_recordings_are_reported_not_retried_elsewhere(services):
    services.bad_audio = True
    with pytest.raises(InvalidAudioError):
        run(local_clone.LocalVoiceClone().clone_voice("me", [("a.wav", b"RIFF", "audio/wav")]))
    assert services.made("voice-clone", "POST", "/voices") == []


def test_omnivoice_gets_urdu_in_urdu_script(services):
    run(local_clone.LocalVoiceClone().synthesize("Hello! آپ کیسے ہیں؟", VOICE))
    assert sent(services, "gpu.example.trycloudflare.com") == [
        {"voice_id": VOICE, "text": "Hello!", "language_id": "en"},
        {"voice_id": VOICE, "text": "آپ کیسے ہیں؟", "language_id": "ur"},
    ]
    assert sent(services, "voice-clone") == []


def test_omnivoice_gets_roman_urdu_in_urdu_script_from_gemini(services, monkeypatch):
    async def to_urdu(text):
        return "آپ کیسے ہیں؟"

    monkeypatch.setattr(pronounce, "to_urdu_script", to_urdu)
    run(local_clone.LocalVoiceClone().synthesize("Aap kaise hain?", VOICE))
    assert sent(services, "gpu.example.trycloudflare.com")[0]["language_id"] == "ur"


def test_omnivoice_without_gemini_gets_the_hindi_spelling(services):
    run(local_clone.LocalVoiceClone().synthesize("Aap kaise hain?", VOICE))
    assert sent(services, "gpu.example.trycloudflare.com") == [
        {"voice_id": VOICE, "text": "आप कैसे हैं?", "language_id": "hi"}
    ]


@pytest.mark.parametrize("problem", ["down", "missing_voice"])
def test_speech_falls_back_to_the_laptop(services, problem):
    getattr(services, problem).add("gpu.example.trycloudflare.com")
    audio = run(local_clone.LocalVoiceClone().synthesize("آپ کیسے ہیں؟", VOICE))
    assert audio.data[:4] == b"RIFF"
    # Chatterbox on the laptop reads Urdu from Devanagari.
    assert sent(services, "voice-clone") == [{"voice_id": VOICE, "text": "आप कैसे हैं?", "language_id": "hi"}]


def test_both_off_is_an_error(services):
    services.down.update({"gpu.example.trycloudflare.com", "voice-clone"})
    with pytest.raises(VoiceUnavailableError):
        run(local_clone.LocalVoiceClone().synthesize("Hello there.", VOICE))


def test_missing_everywhere_is_voice_not_found(services):
    services.missing_voice.update({"gpu.example.trycloudflare.com", "voice-clone"})
    with pytest.raises(VoiceNotFoundError):
        run(local_clone.LocalVoiceClone().synthesize("Hello there.", VOICE))


def test_speech_falls_back_when_the_gpu_never_connects(services):
    services.connect_timeout.add("gpu.example.trycloudflare.com")
    audio = run(local_clone.LocalVoiceClone().synthesize("Hello there.", VOICE))
    assert audio.data[:4] == b"RIFF"
    assert sent(services, "voice-clone") == [{"voice_id": VOICE, "text": "Hello there.", "language_id": "en"}]


def test_delete_while_the_gpu_is_off_still_deletes_on_the_laptop_but_reports_it(services):
    # The GPU copy (e.g. on Google Drive) is still there, so the delete must not count as done.
    services.down.add("gpu.example.trycloudflare.com")
    with pytest.raises(VoiceUnavailableError):
        local_clone.LocalVoiceClone().delete_voice(VOICE)
    assert len(services.made("voice-clone", "DELETE", f"/voices/{VOICE}")) == 1


def test_delete_on_both_services(services):
    local_clone.LocalVoiceClone().delete_voice(VOICE)
    assert len(services.made("gpu.example.trycloudflare.com", "DELETE", f"/voices/{VOICE}")) == 1
    assert len(services.made("voice-clone", "DELETE", f"/voices/{VOICE}")) == 1


def test_a_voice_the_gpu_could_not_delete_is_retried_until_gone(services, db_session):
    from sqlalchemy import select

    from app.models import PendingVoiceDeletion
    from app.services import voice_clone_service

    services.down.add("gpu.example.trycloudflare.com")
    assert voice_clone_service.delete_at_provider(f"local:{VOICE}", "clone") is False
    [pending] = db_session.scalars(select(PendingVoiceDeletion)).all()
    assert pending.voice_clone_id == f"local:{VOICE}" and pending.attempts == 1

    assert voice_clone_service.retry_pending_deletions() == 0  # GPU still off
    assert db_session.scalars(select(PendingVoiceDeletion)).one().attempts == 2

    services.down.clear()  # the GPU is back
    assert voice_clone_service.retry_pending_deletions() == 1
    assert db_session.scalars(select(PendingVoiceDeletion)).all() == []
    assert len(services.made("gpu.example.trycloudflare.com", "DELETE", f"/voices/{VOICE}")) == 3


def test_delete_fails_only_when_no_service_can(services):
    services.down.update({"gpu.example.trycloudflare.com", "voice-clone"})
    with pytest.raises(VoiceUnavailableError):
        local_clone.LocalVoiceClone().delete_voice(VOICE)


def test_engine_is_asked_once(services):
    for _ in range(3):
        run(local_clone.LocalVoiceClone().synthesize("Hello there.", VOICE))
    assert len(services.made("gpu.example.trycloudflare.com", "GET", "/health")) == 1


def test_new_voice_gets_our_transcript_on_every_service(services, monkeypatch):
    from types import SimpleNamespace

    from app.voice import speech_to_text

    original = services.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/reference"):
            services.requests.append(request)
            return httpx.Response(200, content=SPEECH_WAV, headers={"content-type": "audio/wav"})
        if request.method == "PUT" and request.url.path.endswith("/transcript"):
            services.requests.append(request)
            return httpx.Response(204)
        return original(request)

    monkeypatch.setattr(local_clone, "_transport", httpx.MockTransport(handle))

    async def fake_stt(data, filename, content_type, **kwargs):
        assert data == SPEECH_WAV
        return SimpleNamespace(text="آپ کیسے ہیں؟", language="ur")

    monkeypatch.setattr(speech_to_text, "transcribe_audio", fake_stt)
    voice = run(local_clone.LocalVoiceClone().clone_voice("me", [("a.wav", b"RIFF", "audio/wav")]))
    puts = [r for r in services.requests if r.method == "PUT"]
    assert {r.url.host for r in puts} == {"gpu.example.trycloudflare.com", "voice-clone"}
    assert all(json.loads(r.content) == {"text": "آپ کیسے ہیں؟"} for r in puts)
    assert all(r.url.path == f"/voices/{voice}/transcript" for r in puts)


def test_transcript_failure_never_breaks_cloning(services, monkeypatch):
    from app.voice import speech_to_text
    from app.voice.base import VoiceTimeoutError

    async def slow_stt(*args, **kwargs):
        raise VoiceTimeoutError("slow")

    monkeypatch.setattr(speech_to_text, "transcribe_audio", slow_stt)
    # The fake services have no /reference endpoint (an older service): cloning still works.
    assert len(run(local_clone.LocalVoiceClone().clone_voice("me", [("a.wav", b"RIFF", "audio/wav")]))) == 32
