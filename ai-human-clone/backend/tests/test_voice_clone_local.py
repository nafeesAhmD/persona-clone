"""Free self-hosted voice cloning (local Chatterbox service) and the provider abstraction.

The local service is an httpx.MockTransport (FakeLocal below); ElevenLabs is the
FakeElevenLabs from tests/test_voice_clone.py. Samples are real WAVs, so validation,
the WAV conversion and the MP3 encoding of the service's WAV run for real.
"""

import io
import json
import uuid
import wave

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import CloneProfile
from app.services.voice_clone_service import clone_limiter
from app.voice import routing, text_to_speech
from app.voice.providers import elevenlabs, local_clone
from app.voice.transliterate import urdu_to_devanagari
from tests.conftest import tone_wav
from tests.test_voice_clone import KEY, VOICE, FakeElevenLabs, new_clone, upload

URL = "http://voice-clone:8100"
TOKEN = "svc-token-secret-456"
HEX = "0123456789abcdef0123456789abcdef"
HEX2 = "fedcba9876543210fedcba9876543210"
SPEECH_WAV = tone_wav(0.5, 24_000)


class FakeLocal:
    """Records every request; answers like the local voice-clone service. `fail[kind] = status`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, int] = {}
        self.next_voice = HEX

    def kind(self, request: httpx.Request) -> str:
        path = request.url.path
        if request.method == "POST" and path == "/voices":
            return "clone"
        if request.method == "POST" and path == "/synthesize":
            return "tts"
        if request.method == "DELETE" and path.startswith("/voices/"):
            return "delete"
        return "other"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        kind = self.kind(request)
        if kind in self.fail:
            return httpx.Response(self.fail[kind], json={"detail": f"echo {TOKEN}"})
        if kind == "clone":
            return httpx.Response(201, json={"voice_id": self.next_voice, "reference_seconds": 35.0})
        if kind == "tts":
            return httpx.Response(200, content=SPEECH_WAV, headers={"content-type": "audio/wav"})
        if kind == "delete":
            return httpx.Response(204)
        return httpx.Response(404)

    def of(self, kind: str) -> list[httpx.Request]:
        return [r for r in self.requests if self.kind(r) == kind]


@pytest.fixture
def local(monkeypatch) -> FakeLocal:
    fake = FakeLocal()
    settings = get_settings()
    monkeypatch.setattr(settings, "local_voice_clone_url", URL)
    monkeypatch.setattr(settings, "voice_clone_service_token", TOKEN)
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    monkeypatch.setattr(settings, "voice_clone_provider", "auto")
    monkeypatch.setattr(settings, "voice_llm_transliteration", False)  # rule-based spelling, no Gemini
    monkeypatch.setattr(settings, "local_voice_clone_fallback_url", None)
    local_clone.reset_engine_cache()
    monkeypatch.setattr(local_clone, "_transport", httpx.MockTransport(fake.handle))
    clone_limiter.reset()
    yield fake
    clone_limiter.reset()


@pytest.fixture
def eleven(monkeypatch) -> FakeElevenLabs:
    fake = FakeElevenLabs()
    monkeypatch.setattr(elevenlabs, "_transport", httpx.MockTransport(fake.handle))
    return fake


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def cloned_locally(client: TestClient) -> str:
    clone_id = new_clone(client)
    response = upload(client, clone_id)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready", response.text
    return clone_id


def stored(db_session: Session, clone_id: str) -> CloneProfile:
    db_session.expire_all()
    return db_session.get(CloneProfile, uuid.UUID(clone_id))


def no_secrets_in(response) -> None:
    assert TOKEN not in response.text and KEY not in response.text and "echo" not in response.text


# --- Provider selection -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("choice", "key", "url", "expected"),
    [
        ("auto", None, None, None),
        ("auto", None, URL, "local"),
        ("auto", KEY, URL, "elevenlabs"),
        ("auto", KEY, None, "elevenlabs"),
        ("local", KEY, URL, "local"),
        ("local", KEY, None, None),
        ("elevenlabs", KEY, URL, "elevenlabs"),
        ("elevenlabs", None, URL, None),
        ("none", KEY, URL, None),
    ],
)
def test_provider_selection(monkeypatch, choice, key, url, expected):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_clone_provider", choice)
    monkeypatch.setattr(settings, "elevenlabs_api_key", key)
    monkeypatch.setattr(settings, "local_voice_clone_url", url)
    assert routing.active_provider() == expected


def test_provider_setting_is_validated():
    assert Settings(voice_clone_provider=" Local ").voice_clone_provider == "local"
    assert Settings(voice_clone_provider="").voice_clone_provider == "auto"
    assert Settings(local_voice_clone_url="", voice_clone_service_token=" ").local_voice_clone_url is None
    with pytest.raises(ValidationError):
        Settings(voice_clone_provider="openvoice")


def test_stored_ids_are_provider_prefixed():
    assert routing.split("local:" + HEX) == ("local", HEX)
    assert routing.split("elevenlabs:" + VOICE) == ("elevenlabs", VOICE)
    assert routing.split(VOICE) == ("elevenlabs", VOICE)  # legacy, unprefixed
    assert routing.cloned_voice_ref(VOICE) == f"elevenlabs:{VOICE}"
    assert routing.is_cloned("local:" + HEX) and not routing.is_cloned("alto")


def test_status_and_mobile_config_with_local(owner: TestClient, local: FakeLocal):
    clone_id = new_clone(owner)
    status = owner.get(f"/api/clones/{clone_id}/voice/clone").json()
    assert status["available"] is True and status["provider"] == "local"
    assert status["model"] == "chatterbox-multilingual" and status["status"] == "none"
    assert owner.get("/api/mobile/config").json()["voice"]["voice_cloning"] is True


def test_unavailable_message_names_both_options(owner: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_clone_provider", "none")
    monkeypatch.setattr(get_settings(), "local_voice_clone_url", URL)
    clone_id = new_clone(owner)
    response = upload(owner, clone_id)
    assert response.status_code == 503
    assert "ELEVENLABS_API_KEY or the local voice-clone service" in response.json()["detail"]
    assert owner.get("/api/mobile/config").json()["voice"]["voice_cloning"] is False


# --- Cloning and speaking locally -------------------------------------------------------


def test_clone_via_local_service(owner: TestClient, local: FakeLocal, db_session: Session):
    clone_id = new_clone(owner)
    webm = __import__("tests.test_voice", fromlist=["transcode"]).transcode(tone_wav(20.0), "webm", "libopus", 48_000)
    files = [("files", ("a.wav", tone_wav(15.0, 44_100), "audio/wav")), ("files", ("b.webm", webm, "audio/webm"))]
    response = owner.post(f"/api/clones/{clone_id}/voice/clone", files=files, data={"consent": "true"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready" and body["provider"] == "local" and body["use_cloned_voice"] is True
    no_secrets_in(response)

    [request] = local.of("clone")
    assert str(request.url).startswith(URL) and request.headers["x-service-token"] == TOKEN
    content = request.content
    assert content.count(b'name="files"') == 2 and content.count(b"Content-Type: audio/wav") == 2
    assert webm not in content  # converted, not the original
    # Every part is a mono 16-bit WAV.
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts = [p for p in content.split(b"--" + boundary) if b"RIFF" in p]
    assert len(parts) == 2
    for part in parts:
        wav = part[part.index(b"RIFF"):].rstrip(b"\r\n")
        with wave.open(io.BytesIO(wav)) as audio:
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2

    assert stored(db_session, clone_id).voice_clone_id == f"local:{HEX}"
    settings = owner.get(f"/api/clones/{clone_id}/voice/settings").json()
    assert settings["voice_id"] == f"local:{HEX}" and settings["voice_provider"] == "local"
    assert settings["voice_type"] == "custom" and settings["voices"][0]["id"] == f"local:{HEX}"
    assert "on this server" in settings["voices"][0]["description"]


def test_urdu_script_is_spoken_as_hindi(owner: TestClient, local: FakeLocal, tts):
    clone_id = cloned_locally(owner)
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "آپ کیسے ہیں؟"})
    assert response.status_code == 200, response.text
    [request] = local.of("tts")
    assert request.headers["x-service-token"] == TOKEN
    assert json.loads(request.content) == {"voice_id": HEX, "text": "आप कैसे हैं?", "language_id": "hi"}
    assert tts.calls == []
    audio = owner.get(response.json()["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"  # WAV encoded to MP3


def test_roman_urdu_is_spoken_as_hindi(owner: TestClient, local: FakeLocal):
    clone_id = cloned_locally(owner)
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Aap kaise hain? Main theek hoon."})
    assert response.status_code == 200, response.text
    body = json.loads(local.of("tts")[-1].content)
    assert body["language_id"] == "hi" and body["text"] == "आप कैसे हैं? मैं ठीक हूँ."


def test_mixed_english_and_roman_urdu_keep_their_own_language(owner: TestClient, local: FakeLocal):
    clone_id = cloned_locally(owner)
    text = "Hello! This is my AI clone speaking with my own voice. Assalam-o-Alaikum, aap kaise hain?"
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": text}).status_code == 200
    sent = [json.loads(request.content) for request in local.of("tts")]
    assert [(body["language_id"], body["text"]) for body in sent] == [
        ("en", "Hello! This is my AI clone speaking with my own voice."),
        ("hi", "अस्सलाम-ओ-अलैकुम, आप कैसे हैं?"),
    ]


def test_segments():
    assert local_clone.segments("Hello there", None) == [("Hello there", "en")]
    assert local_clone.segments("Aap kaise hain? Main theek hoon.", None) == [("आप कैसे हैं? मैं ठीक हूँ.", "hi")]
    assert local_clone.segments("Shukriya! Thank you so much.", "ur") == [("शुक्रिया!", "hi"), ("Thank you so much.", "en")]
    assert local_clone.segments("Bonjour", "fr") == [("Bonjour", "fr")]
    assert local_clone.segments("یہ ٹھیک ہے", None) == [("यह ठीक है", "hi")]


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [(None, "Hello there", "en"), ("ur", "Hello there", "en"), ("en", "Hi", "en")],
)
def test_latin_text_is_spoken_as_english(owner: TestClient, local: FakeLocal, language, text, expected):
    clone_id = cloned_locally(owner)
    if language:
        owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_language": language})
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": text}).status_code == 200
    body = json.loads(local.of("tts")[-1].content)
    assert body["language_id"] == expected and body["text"] == text


def test_language_mapping():
    assert local_clone.language_for("Hello", None) == ("Hello", "en")
    assert local_clone.language_for("Bonjour", "fr") == ("Bonjour", "fr")
    assert local_clone.language_for("Hola", "es-ES") == ("Hola", "es")
    assert local_clone.language_for("Salam", "ur") == ("सलाम", "hi")  # Roman Urdu
    assert local_clone.language_for("Hi", "xx") == ("Hi", "en")
    assert local_clone.language_for("مرحبا", "ar") == ("مرحبا", "ar")  # Arabic stays Arabic
    assert local_clone.language_for("یہ ٹھیک ہے", "en") == ("यह ठीक है", "hi")


def test_local_speech_uses_the_longer_timeout(owner: TestClient, local: FakeLocal, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_timeout_seconds", 7.0)
    monkeypatch.setattr(settings, "local_voice_clone_timeout_seconds", 321.0)
    seen: list[float] = []
    real_wait_for = text_to_speech.asyncio.wait_for

    async def spy(awaitable, timeout):
        seen.append(timeout)
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(text_to_speech.asyncio, "wait_for", spy)
    clone_id = cloned_locally(owner)
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 200
    assert seen == [321.0]
    assert local.of("tts")[0].extensions["timeout"]["read"] == 321.0
    # A prebuilt voice keeps VOICE_TIMEOUT_SECONDS.
    owner.patch(f"/api/clones/{clone_id}/voice/clone", json={"use_cloned_voice": False})
    owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"})
    assert seen[-1] == 7.0


def test_long_answers_are_split_and_joined(owner: TestClient, local: FakeLocal):
    clone_id = cloned_locally(owner)
    text = " ".join(f"This is sentence number {i} of a long answer." for i in range(10))  # 449 characters (voice test max 500)
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": text}).status_code == 200
    sent = [json.loads(r.content)["text"] for r in local.of("tts")]
    assert len(sent) > 1 and all(1 <= len(piece) <= local_clone.MAX_CHUNK_CHARACTERS for piece in sent)
    assert " ".join(sent) == text


def test_chunks():
    assert local_clone.chunks("One. Two! Three?", 9) == ["One. Two!", "Three?"]
    long = "word " * 300
    assert all(len(piece) <= 100 for piece in local_clone.chunks(long, 100))
    assert local_clone.chunks("   ") == []


# --- Deleting at the right provider -----------------------------------------------------


def _with_voice(db_session: Session, clone_id: str, voice_clone_id: str) -> None:
    clone = stored(db_session, clone_id)
    clone.voice_clone_id, clone.voice_clone_status, clone.use_cloned_voice = voice_clone_id, "ready", True
    db_session.commit()


@pytest.mark.parametrize(
    ("voice_clone_id", "provider", "path"),
    [
        (VOICE, "elevenlabs", f"/v1/voices/{VOICE}"),  # legacy, unprefixed
        (f"elevenlabs:{VOICE}", "elevenlabs", f"/v1/voices/{VOICE}"),
        (f"local:{HEX}", "local", f"/voices/{HEX}"),
    ],
)
def test_delete_at_the_provider_that_made_it(
    owner: TestClient, local: FakeLocal, eleven: FakeElevenLabs, db_session: Session, monkeypatch,
    voice_clone_id, provider, path,
):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", KEY)
    # Whatever provider is active now, the voice is deleted where it was made.
    monkeypatch.setattr(get_settings(), "voice_clone_provider", "local" if provider == "elevenlabs" else "elevenlabs")
    clone_id = new_clone(owner)
    _with_voice(db_session, clone_id, voice_clone_id)
    status = owner.get(f"/api/clones/{clone_id}/voice/clone").json()
    assert status["provider"] == provider
    assert owner.delete(f"/api/clones/{clone_id}/voice/clone").status_code == 204
    fake, other = (eleven, local) if provider == "elevenlabs" else (local, eleven)
    assert [r.url.path for r in fake.of("delete")] == [path] and other.of("delete") == []
    assert stored(db_session, clone_id).voice_clone_id is None


def test_legacy_voice_still_speaks_with_elevenlabs(
    owner: TestClient, local: FakeLocal, eleven: FakeElevenLabs, db_session: Session, monkeypatch
):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", KEY)
    clone_id = new_clone(owner)
    _with_voice(db_session, clone_id, VOICE)
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 200
    [request] = eleven.of("tts")
    assert request.url.path == f"/v1/text-to-speech/{VOICE}" and local.of("tts") == []


def test_replacing_after_a_provider_switch_deletes_the_old_local_voice(
    owner: TestClient, local: FakeLocal, eleven: FakeElevenLabs, db_session: Session, monkeypatch
):
    clone_id = cloned_locally(owner)
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", KEY)  # auto now picks ElevenLabs
    assert upload(owner, clone_id).json()["provider"] == "elevenlabs"
    assert [r.url.path for r in local.of("delete")] == [f"/voices/{HEX}"]
    assert stored(db_session, clone_id).voice_clone_id == f"elevenlabs:{VOICE}"


def test_replacing_a_local_voice(owner: TestClient, local: FakeLocal, db_session: Session):
    clone_id = cloned_locally(owner)
    local.next_voice = HEX2
    assert upload(owner, clone_id).json()["status"] == "ready"
    assert [r.url.path for r in local.of("delete")] == [f"/voices/{HEX}"]
    assert stored(db_session, clone_id).voice_clone_id == f"local:{HEX2}"


def test_withdrawing_consent_deletes_local_voice(owner: TestClient, local: FakeLocal):
    clone_id = cloned_locally(owner)
    response = owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": False})
    assert response.status_code == 200 and response.json()["voice_clone"]["status"] == "none"
    [delete] = local.of("delete")
    assert delete.url.path == f"/voices/{HEX}" and delete.headers["x-service-token"] == TOKEN


def test_deleting_the_clone_deletes_local_voice(owner: TestClient, local: FakeLocal, db_session):
    clone_id = cloned_locally(owner)
    local.fail["delete"] = 503  # an outage never blocks deleting the clone
    assert owner.delete(f"/api/clones/{clone_id}").status_code == 204
    assert [r.url.path for r in local.of("delete")] == [f"/voices/{HEX}"]
    # ...but the voice is kept pending and deleted once the service is back.
    from sqlalchemy import select

    from app.models import PendingVoiceDeletion
    from app.voice.cleanup import retry_pending_voice_deletions

    assert db_session.scalars(select(PendingVoiceDeletion.voice_clone_id)).all() == [f"local:{HEX}"]
    del local.fail["delete"]
    assert retry_pending_voice_deletions() == 1
    assert db_session.scalars(select(PendingVoiceDeletion)).all() == []


def test_local_voice_falls_back_when_service_removed(owner: TestClient, local: FakeLocal, tts, monkeypatch):
    clone_id = cloned_locally(owner)
    monkeypatch.setattr(get_settings(), "local_voice_clone_url", None)
    assert owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"}).status_code == 200
    assert tts.calls[-1]["voice"] == "alto" and local.of("tts") == []


# --- Errors are safe --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "message"),
    [(400, "quiet room"), (413, "too large"), (401, "isn't set up"), (503, "starting"), (500, "temporarily unavailable")],
)
def test_clone_errors_are_safe(owner: TestClient, local: FakeLocal, status, message):
    clone_id = new_clone(owner)
    local.fail["clone"] = status
    response = upload(owner, clone_id)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed" and message in body["error"] and body["use_cloned_voice"] is False
    no_secrets_in(response)


@pytest.mark.parametrize(("status", "code", "message"), [(503, 503, "starting"), (504, 504, "too long"), (500, 503, "")])
def test_speech_errors_are_safe(owner: TestClient, local: FakeLocal, status, code, message):
    clone_id = cloned_locally(owner)
    local.fail["tts"] = status
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"})
    assert response.status_code == code and message in response.json()["detail"]
    no_secrets_in(response)


@pytest.mark.parametrize(
    ("error", "code"), [(httpx.ConnectError, 503), (httpx.ReadTimeout, 504)]
)
def test_service_down_or_slow(owner: TestClient, local: FakeLocal, monkeypatch, error, code):
    clone_id = cloned_locally(owner)

    def broken(request: httpx.Request) -> httpx.Response:
        raise error("boom", request=request)

    monkeypatch.setattr(local_clone, "_transport", httpx.MockTransport(broken))
    response = owner.post(f"/api/clones/{clone_id}/voice/test", json={"text": "Hi"})
    assert response.status_code == code
    no_secrets_in(response)
    assert "voice-clone:8100" not in response.text


def test_voice_chat_keeps_text_when_local_voice_fails(owner: TestClient, local: FakeLocal):
    clone_id = cloned_locally(owner)
    local.fail["tts"] = 503
    response = owner.post(
        f"/api/clones/{clone_id}/voice/chat", files={"audio": ("voice.wav", tone_wav(1.0), "audio/wav")}
    )
    assert response.status_code == 200
    assert response.json()["audio_url"] is None and response.json()["tts_error"]


# --- Transliteration --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("urdu", "devanagari"),
    [
        ("آپ کیسے ہیں؟", "आप कैसे हैं?"),
        ("میرا نام احمد ہے۔", "मेरा नाम अहमद है।"),
        ("السلام علیکم! میں آپ کی مدد کر سکتا ہوں۔", "अस्सलाम अलैकुम! में आप की मदद कर सकता हूँ।"),
        ("بھائی، آواز جواب کتابیں ۱۲۳", "भाई, आवाज़ जवाब कताबें 123"),
        ("کھانا گھر تھا اچھّا", "खाना घर था अच्छा"),
        ("آئے گئی جاؤ بعد", "आए गई जाओ बाद"),
        ("AI کلون ok", "AI कलोन ok"),
        ("ﺑﺎﺕ", "बात"),  # presentation forms
        ("اُس نے کِتاب پڑھی", "उस ने किताब पढ़ी"),  # short-vowel marks
    ],
)
def test_transliteration(urdu: str, devanagari: str):
    assert urdu_to_devanagari(urdu) == devanagari


def test_transliteration_leaves_no_arabic_script():
    text = "پاکستان ایک خوبصورت ملک ہے، اور یہاں کے لوگ بہت مہمان نواز ہیں۔"
    result = urdu_to_devanagari(text)
    assert not any("؀" <= c <= "ۿ" for c in result)
    assert result.startswith("पाक") and result.endswith("हैं।")
