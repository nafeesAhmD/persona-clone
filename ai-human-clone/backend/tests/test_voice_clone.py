"""Personal voice clone (ElevenLabs Instant Voice Cloning) and TTS routing to the cloned voice.

ElevenLabs is an httpx.MockTransport (FakeElevenLabs below); the prebuilt voice is
tests/conftest.FakeTTS. The uploaded samples are real WAVs (tests.conftest.tone_wav),
so validation and duration checks run for real.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CloneProfile
from app.services.voice_clone_service import clone_limiter
from app.voice.audio import encode_mp3
from app.voice.providers import elevenlabs
from tests.conftest import USER, tone_wav
from tests.test_voice import transcode

KEY = "xi-test-secret-key-123"
VOICE = "vc_owner_123"
CLONE = {"name": "Ayaan AI", "profession": "Software Developer", "owner_consent": True}
SAMPLE = tone_wav(35.0)
MP3 = encode_mp3(tone_wav(0.5, 24_000))


class FakeElevenLabs:
    """Records every request; answers like the ElevenLabs API. Set `fail[kind] = status`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, int] = {}
        self.next_voice = VOICE

    def kind(self, request: httpx.Request) -> str:
        path = request.url.path
        if request.method == "POST" and path == "/v1/voices/add":
            return "clone"
        if request.method == "POST" and path.startswith("/v1/text-to-speech/"):
            return "tts"
        if request.method == "DELETE" and path.startswith("/v1/voices/"):
            return "delete"
        return "other"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        kind = self.kind(request)
        if kind in self.fail:
            return httpx.Response(self.fail[kind], json={"detail": {"message": f"echo {KEY}"}})
        if kind == "clone":
            return httpx.Response(200, json={"voice_id": self.next_voice, "requires_verification": False})
        if kind == "tts":
            return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})
        if kind == "delete":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    def of(self, kind: str) -> list[httpx.Request]:
        return [r for r in self.requests if self.kind(r) == kind]


@pytest.fixture
def eleven(monkeypatch) -> FakeElevenLabs:
    fake = FakeElevenLabs()
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", KEY)
    monkeypatch.setattr(elevenlabs, "_transport", httpx.MockTransport(fake.handle))
    clone_limiter.reset()
    yield fake
    clone_limiter.reset()


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def new_clone(client: TestClient, *, consent: bool = True, voice: bool = True) -> str:
    response = client.post("/api/clones", json=CLONE)
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    if consent:
        settings = {"voice_consent_given": True, **({"voice_enabled": True} if voice else {})}
        assert client.patch(f"/api/clones/{clone_id}/voice/settings", json=settings).status_code == 200
    return clone_id


def upload(client: TestClient, clone_id: str, samples=(SAMPLE,), *, consent: str = "true", **form):
    files = [("files", (f"sample{i}.wav", data, "audio/wav")) for i, data in enumerate(samples)]
    return client.post(f"/api/clones/{clone_id}/voice/clone", files=files, data={"consent": consent, **form})


def cloned(client: TestClient, eleven: FakeElevenLabs) -> str:
    clone_id = new_clone(client)
    response = upload(client, clone_id)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"
    return clone_id


def no_key_in(response: httpx.Response) -> None:
    assert KEY not in response.text


# --- Availability, consent and recordings ---------------------------------------------


def test_status_without_key_and_clone_unavailable(owner: TestClient):
    clone_id = new_clone(owner)
    status = owner.get(f"/api/clones/{clone_id}/voice/clone").json()
    assert status["available"] is False and status["status"] == "none" and status["provider"] is None
    assert status["min_seconds"] == 30 and status["max_seconds"] == 300 and status["max_files"] == 5
    assert status["model"] == "eleven_v3"
    response = upload(owner, clone_id)
    assert response.status_code == 503
    assert "ELEVENLABS_API_KEY" in response.json()["detail"]
    assert owner.get("/api/mobile/config").json()["voice"]["voice_cloning"] is False


def test_mobile_config_reports_cloning(owner: TestClient, eleven: FakeElevenLabs):
    assert owner.get("/api/mobile/config").json()["voice"]["voice_cloning"] is True


def test_needs_voice_consent_then_clone_consent(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = new_clone(owner, consent=False)
    assert upload(owner, clone_id).status_code == 403
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True})
    response = upload(owner, clone_id, consent="false")
    assert response.status_code == 400 and "permission" in response.json()["detail"]
    assert eleven.requests == []


def test_recording_length_and_count(owner: TestClient, eleven: FakeElevenLabs, monkeypatch):
    clone_id = new_clone(owner)
    response = upload(owner, clone_id, (tone_wav(10.0), tone_wav(8.0)))
    assert response.status_code == 400
    assert "Record at least 30 seconds in total (you have 18)" in response.json()["detail"]
    monkeypatch.setattr(get_settings(), "voice_clone_max_seconds", 40.0)
    response = upload(owner, clone_id, (tone_wav(25.0), tone_wav(25.0)))
    assert response.status_code == 400 and "too long" in response.json()["detail"]
    response = upload(owner, clone_id, [tone_wav(1.0)] * 6)
    assert response.status_code == 400 and "at most 5" in response.json()["detail"]
    bad = owner.post(
        f"/api/clones/{clone_id}/voice/clone",
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
        data={"consent": "true"},
    )
    assert bad.status_code == 415
    assert eleven.requests == []


def test_browser_mic_clips(owner: TestClient, eleven: FakeElevenLabs):
    """What the frontend sends: recording-N.webm clips (Opus, up to 60 s each) and form strings."""
    clip = transcode(tone_wav(20.0), "webm", "libopus", 48_000)
    files = [("files", (f"recording-{i}.webm", clip, "audio/webm;codecs=opus")) for i in (1, 2)]
    response = owner.post(
        f"/api/clones/{new_clone(owner)}/voice/clone",
        files=files,
        data={"consent": "true", "remove_background_noise": "false"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"
    [request] = eleven.of("clone")
    assert request.content.count(b'filename="recording-') == 2 and clip in request.content


def test_samples_longer_than_chat_limit_are_accepted(owner: TestClient, eleven: FakeElevenLabs):
    # One 70 s sample: longer than MAX_AUDIO_DURATION_SECONDS (60) for chat, fine for cloning.
    clone_id = new_clone(owner)
    assert upload(owner, clone_id, (tone_wav(70.0),)).json()["status"] == "ready"


# --- Creating, using and deleting the cloned voice -------------------------------------


def test_create_clone(owner: TestClient, eleven: FakeElevenLabs, db_session: Session):
    clone_id = new_clone(owner)
    response = upload(owner, clone_id, (SAMPLE, tone_wav(5.0)), remove_background_noise="true")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready" and body["use_cloned_voice"] is True and body["error"] is None
    assert body["provider"] == "elevenlabs" and body["consent_at"] and body["available"] is True
    no_key_in(response)

    [request] = eleven.of("clone")
    assert request.headers["xi-api-key"] == KEY
    content = request.content
    assert content.count(b'name="files"') == 2
    assert b'name="remove_background_noise"\r\n\r\ntrue' in content
    assert b"Ayaan AI" in content
    assert SAMPLE in content  # the original recording, not a re-encoded copy

    clone = db_session.get(CloneProfile, __import__("uuid").UUID(clone_id))
    assert clone.voice_clone_id == f"elevenlabs:{VOICE}" and clone.voice_id == "alto"  # prebuilt voice kept

    settings = owner.get(f"/api/clones/{clone_id}/voice/settings").json()
    assert settings["voice_type"] == "custom" and settings["voice_id"] == f"elevenlabs:{VOICE}"
    assert settings["voice_provider"] == "elevenlabs"
    assert settings["voices"][0] == {
        "id": f"elevenlabs:{VOICE}",
        "name": "My voice (cloned)",
        "description": settings["voices"][0]["description"],
        "is_custom": True,
    }
    assert settings["voice_clone"]["status"] == "ready"


def test_voice_test_speaks_with_cloned_voice(owner: TestClient, eleven: FakeElevenLabs, tts):
    clone_id = cloned(owner, eleven)
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_language": "ur"})
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Assalam o alaikum"})
    assert response.status_code == 200, response.text
    [request] = eleven.of("tts")
    assert request.url.path == f"/v1/text-to-speech/{VOICE}"
    assert request.url.params["output_format"] == "mp3_44100_128"
    assert request.headers["xi-api-key"] == KEY
    body = json.loads(request.content)
    assert body["model_id"] == "eleven_v3" and body["language_code"] == "ur"
    assert body["text"] == "Assalam o alaikum" and body["voice_settings"]["similarity_boost"] == 0.8
    assert tts.calls == []
    audio = owner.get(response.json()["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == MP3  # stored as ElevenLabs sent it (no re-encoding)


def test_voice_chat_and_spoken_replies_use_cloned_voice(owner: TestClient, eleven: FakeElevenLabs, tts):
    clone_id = cloned(owner, eleven)
    response = owner.post(
        f"/api/clones/{clone_id}/voice/chat", files={"audio": ("voice.wav", tone_wav(1.0), "audio/wav")}
    )
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["audio_url"] and reply["tts_error"] is None
    assert len(eleven.of("tts")) == 1 and tts.calls == []

    # "Play" on a saved answer: same voice; the cached recording is reused.
    speech = owner.post(f"/api/conversations/{reply['conversation_id']}/messages/{reply['message']['id']}/speech")
    assert speech.status_code == 200 and len(eleven.of("tts")) == 1


def test_turning_cloned_voice_off_returns_to_prebuilt(owner: TestClient, eleven: FakeElevenLabs, tts):
    clone_id = cloned(owner, eleven)
    response = owner.patch(f"/api/clones/{clone_id}/voice/clone", json={"use_cloned_voice": False})
    assert response.status_code == 200 and response.json()["use_cloned_voice"] is False
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 200
    assert eleven.of("tts") == [] and tts.calls[-1]["voice"] == "alto"
    settings = owner.get(f"/api/clones/{clone_id}/voice/settings").json()
    assert settings["voice_type"] == "ai_generated" and settings["voice_id"] == "alto"

    # Choosing it in the voice list turns it back on; choosing a prebuilt voice turns it off.
    on = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_id": f"elevenlabs:{VOICE}"})
    assert on.status_code == 200 and on.json()["voice_clone"]["use_cloned_voice"] is True
    off = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_id": "bass"})
    assert off.json()["voice_id"] == "bass" and off.json()["voice_clone"]["use_cloned_voice"] is False
    assert owner.patch(
        f"/api/clones/{clone_id}/voice/settings", json={"voice_id": "elevenlabs:someone-else"}
    ).status_code == 400


def test_use_needs_a_ready_voice(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = new_clone(owner)
    response = owner.patch(f"/api/clones/{clone_id}/voice/clone", json={"use_cloned_voice": True})
    assert response.status_code == 400


def test_without_key_falls_back_to_prebuilt(owner: TestClient, eleven: FakeElevenLabs, tts, monkeypatch):
    clone_id = cloned(owner, eleven)
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", None)
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 200
    assert tts.calls[-1]["voice"] == "alto" and eleven.of("tts") == []


def test_new_clone_replaces_old_voice(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    eleven.next_voice = "vc_second"
    assert upload(owner, clone_id).json()["status"] == "ready"
    [delete] = eleven.of("delete")
    assert delete.url.path == f"/v1/voices/{VOICE}"
    assert owner.get(f"/api/clones/{clone_id}/voice/settings").json()["voice_id"] == "elevenlabs:vc_second"


def test_delete_cloned_voice(owner: TestClient, eleven: FakeElevenLabs, tts):
    clone_id = cloned(owner, eleven)
    assert owner.delete(f"/api/clones/{clone_id}/voice/clone").status_code == 204
    [delete] = eleven.of("delete")
    assert delete.url.path == f"/v1/voices/{VOICE}" and delete.headers["xi-api-key"] == KEY
    status = owner.get(f"/api/clones/{clone_id}/voice/clone").json()
    assert status["status"] == "none" and status["use_cloned_voice"] is False and status["consent_at"] is None
    owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"})
    assert tts.calls[-1]["voice"] == "alto"


def test_delete_clears_locally_when_provider_is_down(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    eleven.fail["delete"] = 500
    assert owner.delete(f"/api/clones/{clone_id}/voice/clone").status_code == 204
    assert owner.get(f"/api/clones/{clone_id}/voice/clone").json()["status"] == "none"


def test_already_deleted_voice_counts_as_deleted(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    eleven.fail["delete"] = 404
    assert owner.delete(f"/api/clones/{clone_id}/voice/clone").status_code == 204


def test_withdrawing_voice_consent_deletes_cloned_voice(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    response = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": False})
    assert response.status_code == 200
    assert response.json()["voice_clone"]["status"] == "none" and response.json()["voice_type"] == "ai_generated"
    assert [r.url.path for r in eleven.of("delete")] == [f"/v1/voices/{VOICE}"]


def test_deleting_the_clone_deletes_cloned_voice(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    eleven.fail["delete"] = 503  # a provider outage never blocks deleting the clone
    assert owner.delete(f"/api/clones/{clone_id}").status_code == 204
    assert [r.url.path for r in eleven.of("delete")] == [f"/v1/voices/{VOICE}"]
    assert owner.get(f"/api/clones/{clone_id}").status_code == 404


def test_only_the_owner(owner: TestClient, eleven: FakeElevenLabs, make_client):
    clone_id = cloned(owner, eleven)
    other = make_client()
    assert other.post(
        "/api/auth/register", json={**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
    ).status_code == 201
    base = f"/api/clones/{clone_id}/voice/clone"
    assert other.get(base).status_code == 404
    assert upload(other, clone_id).status_code == 404
    assert other.patch(base, json={"use_cloned_voice": False}).status_code == 404
    assert other.delete(base).status_code == 404
    assert eleven.of("delete") == [] and len(eleven.of("clone")) == 1


def test_clone_attempts_are_rate_limited(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = new_clone(owner)
    for _ in range(3):
        assert upload(owner, clone_id).status_code == 201
    assert upload(owner, clone_id).status_code == 429


# --- Provider errors ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "isn't set up"), (402, "usage limit"), (422, "quiet room"), (429, "busy"), (500, "temporarily unavailable")],
)
def test_clone_provider_errors_are_safe(owner: TestClient, eleven: FakeElevenLabs, status: int, message: str):
    clone_id = new_clone(owner)
    eleven.fail["clone"] = status
    response = upload(owner, clone_id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed" and message in body["error"] and body["use_cloned_voice"] is False
    no_key_in(response)
    assert "echo" not in response.text


@pytest.mark.parametrize(("status", "code"), [(401, 503), (402, 503), (429, 429), (500, 503)])
def test_tts_provider_errors_are_safe(owner: TestClient, eleven: FakeElevenLabs, status: int, code: int):
    clone_id = cloned(owner, eleven)
    eleven.fail["tts"] = status
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"})
    assert response.status_code == code
    no_key_in(response)
    assert "echo" not in response.text


def test_voice_chat_keeps_text_answer_when_cloned_voice_fails(owner: TestClient, eleven: FakeElevenLabs):
    clone_id = cloned(owner, eleven)
    eleven.fail["tts"] = 500
    response = owner.post(
        f"/api/clones/{clone_id}/voice/chat", files={"audio": ("voice.wav", tone_wav(1.0), "audio/wav")}
    )
    assert response.status_code == 200
    assert response.json()["audio_url"] is None and response.json()["tts_error"]


def test_provider_timeout(owner: TestClient, eleven: FakeElevenLabs, monkeypatch):
    clone_id = cloned(owner, eleven)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(elevenlabs, "_transport", httpx.MockTransport(slow))
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 504
