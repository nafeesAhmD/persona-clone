"""Phase 8: avatars and talking-avatar videos.

TTS is tests/conftest.FakeTTS (a short tone); the lip-sync is the real local
CPU renderer, so jobs produce real MP4 files. Jobs run inline in tests.
"""

import io
import os
import time
import uuid

import av
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.avatar.base import AvatarError, LipSyncRequest, MouthPosition
from app.avatar.providers.http_lipsync import HttpLipSync
from app.avatar.providers.local_lipsync import LocalLipSync, mouth_envelope
from app.avatar.storage import get_avatar_storage
from app.models import AvatarVideoJob, CloneAvatar, CloneProfile
from app.voice.base import VoiceRateLimitError
from tests.conftest import USER, open_to_public, tone_wav

CLONE = {"name": "Ayaan AI", "profession": "Software Developer", "owner_consent": True}


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


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (320, 400), exif: bool = False) -> bytes:
    image = Image.new("RGB", size, (180, 140, 120))
    buffer = io.BytesIO()
    kwargs = {}
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCamera"  # Make
        kwargs["exif"] = data
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def new_clone(client: TestClient, *, consent: bool = True, voice: bool = True, **overrides) -> str:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    if voice:
        assert client.patch(
            f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}
        ).status_code == 200
    if consent:
        assert client.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_consent_given": True}).status_code == 200
    return clone_id


def upload(client: TestClient, clone_id: str, data: bytes | None = None, name: str = "me.png", mime: str = "image/png"):
    return client.post(
        f"/api/clones/{clone_id}/avatar", files={"image": (name, image_bytes() if data is None else data, mime)}
    )


def ready_clone(client: TestClient, **overrides) -> str:
    """A clone with voice, consent, a preset avatar and the avatar turned on."""
    clone_id = new_clone(client, **overrides)
    assert client.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "ayaan"}).status_code == 201
    assert client.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True}).status_code == 200
    return clone_id


def answer(client: TestClient, clone_id: str) -> tuple[str, str]:
    chat = client.post(f"/api/clones/{clone_id}/chat", json={"message": "hello", "conversation_id": None}).json()
    return chat["conversation_id"], chat["message"]["id"]


def video_for(client: TestClient, clone_id: str, conversation_id: str, message_id: str):
    return client.post(
        f"/api/clones/{clone_id}/avatar/video", json={"conversation_id": conversation_id, "message_id": message_id}
    )


def job_of(client: TestClient, clone_id: str, job_id: str) -> dict:
    response = client.get(f"/api/clones/{clone_id}/avatar/jobs/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


# --- Upload and validation ------------------------------------------------------------


@pytest.mark.parametrize(("fmt", "name", "mime"), [("PNG", "me.png", "image/png"), ("JPEG", "me.jpg", "image/jpeg"), ("WEBP", "me.webp", "image/webp")])
def test_upload_avatar_formats(owner: TestClient, fmt, name, mime):
    clone_id = new_clone(owner)
    response = upload(owner, clone_id, image_bytes(fmt), name, mime)
    assert response.status_code == 201, response.text
    avatar = response.json()
    assert avatar["avatar_type"] == "uploaded" and avatar["status"] == "ready" and avatar["is_active"]
    assert (avatar["width"], avatar["height"]) == (320, 400)
    assert 0 < avatar["mouth_x"] < 1 and 0 < avatar["mouth_y"] < 1
    image = owner.get(avatar["image_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


def test_upload_is_normalised_and_metadata_removed(owner: TestClient, storage_dir):
    clone_id = new_clone(owner)
    big = image_bytes("JPEG", (2400, 1800), exif=True)
    avatar = upload(owner, clone_id, big, "photo.jpeg", "image/jpeg").json()
    assert max(avatar["width"], avatar["height"]) == 1024
    assert avatar["width"] % 2 == 0 and avatar["height"] % 2 == 0
    stored = owner.get(avatar["image_url"]).content
    with Image.open(io.BytesIO(stored)) as image:
        assert image.format == "PNG" and not image.getexif()
    files = list((storage_dir / "clones" / clone_id / "avatar").iterdir())
    assert len(files) == 1 and files[0].name != "photo.jpeg"  # generated name


@pytest.mark.parametrize(
    ("data", "name", "mime", "status"),
    [
        (b"not an image at all", "me.png", "image/png", 415),
        (image_bytes("PNG"), "me.jpg", "image/jpeg", 415),  # bytes are PNG
        (image_bytes("PNG"), "me.png", "text/plain", 415),
        (image_bytes("GIF"), "me.gif", "image/gif", 415),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "me.png", "image/png", 400),  # PNG header, broken body
        (image_bytes("PNG", (60, 60)), "me.png", "image/png", 400),  # too small
        (b"", "me.png", "image/png", 400),
    ],
)
def test_invalid_images_are_rejected(owner: TestClient, db_session: Session, data, name, mime, status):
    clone_id = new_clone(owner)
    response = upload(owner, clone_id, data, name, mime)
    assert response.status_code == status, response.text
    assert db_session.scalars(select(CloneAvatar)).all() == []


def test_oversized_image(owner: TestClient, monkeypatch):
    from app.core.config import get_settings

    clone_id = new_clone(owner)
    monkeypatch.setattr(get_settings(), "max_avatar_size_mb", 1)
    noisy = Image.effect_noise((1200, 1200), 100).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, format="PNG")
    response = upload(owner, clone_id, buffer.getvalue())
    assert response.status_code == 413 and "Maximum size is 1 MB" in response.json()["detail"]


def test_presets_and_generated_avatars(owner: TestClient):
    clone_id = new_clone(owner)
    settings = owner.get(f"/api/clones/{clone_id}/avatar").json()
    assert {p["id"] for p in settings["presets"]} >= {"ayaan", "sara"}
    preset = owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "sara"})
    assert preset.status_code == 201 and preset.json()["avatar_type"] == "preset" and preset.json()["face_detected"]
    style = {"skin": "#8d5f45", "hair": "#140f0d", "hair_style": "bun", "background": "#223344", "shirt": "#aa5500"}
    generated = owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"style": style})
    assert generated.status_code == 201 and generated.json()["avatar_type"] == "generated"
    assert owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "nobody"}).status_code == 400
    assert owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"style": {**style, "skin": "red"}}).status_code == 400
    assert owner.post(f"/api/clones/{clone_id}/avatar/generate", json={}).status_code == 400


# --- Consent ------------------------------------------------------------------------


def test_avatar_needs_consent(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner, consent=False)
    assert upload(owner, clone_id).status_code == 403
    assert owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "ayaan"}).status_code == 403
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True}).status_code == 403

    settings = owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_consent_given": True}).json()
    assert settings["avatar_consent_given"] and settings["avatar_consent_at"]
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True}).status_code == 400  # no avatar yet
    assert upload(owner, clone_id).status_code == 201
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True}).json()["avatar_enabled"]

    withdrawn = owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_consent_given": False}).json()
    assert withdrawn["avatar_enabled"] is False and withdrawn["avatar_consent_at"] is None
    db_session.expire_all()
    assert db_session.get(CloneProfile, uuid.UUID(clone_id)).avatar_enabled is False


def test_avatar_settings_changes(owner: TestClient):
    clone_id = new_clone(owner)
    first = upload(owner, clone_id).json()
    second = owner.post(f"/api/clones/{clone_id}/avatar/generate", json={"preset": "sam"}).json()
    settings = owner.get(f"/api/clones/{clone_id}/avatar").json()
    assert settings["active_avatar"]["id"] == second["id"] and len(settings["avatars"]) == 2

    chosen = owner.patch(f"/api/clones/{clone_id}/avatar", json={"active_avatar_id": first["id"]}).json()
    assert chosen["active_avatar"]["id"] == first["id"]
    moved = owner.patch(f"/api/clones/{clone_id}/avatar", json={"mouth_x": 0.4, "mouth_y": 0.7, "mouth_width": 0.2}).json()
    assert (moved["active_avatar"]["mouth_x"], moved["active_avatar"]["mouth_y"]) == (0.4, 0.7)
    assert owner.patch(f"/api/clones/{clone_id}/avatar", json={"mouth_x": 2}).status_code == 400

    owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": True})
    assert owner.delete(f"/api/clones/{clone_id}/avatar").status_code == 204  # the active one
    after = owner.get(f"/api/clones/{clone_id}/avatar").json()
    assert after["active_avatar"]["id"] == second["id"] and after["avatar_enabled"]
    assert owner.delete(f"/api/clones/{clone_id}/avatar/{second['id']}").status_code == 204
    empty = owner.get(f"/api/clones/{clone_id}/avatar").json()
    assert empty["active_avatar"] is None and empty["avatar_enabled"] is False
    assert owner.delete(f"/api/clones/{clone_id}/avatar").status_code == 404


# --- Security -----------------------------------------------------------------------


def test_other_users_cannot_touch_avatars(owner: TestClient, other: TestClient):
    for visibility, expected in (("private", 404), ("public", 403)):
        clone_id = ready_clone(owner, visibility=visibility)
        avatar = owner.get(f"/api/clones/{clone_id}/avatar").json()["active_avatar"]
        base = f"/api/clones/{clone_id}/avatar"
        assert other.get(base).status_code == expected
        assert upload(other, clone_id).status_code == expected
        assert other.patch(base, json={"avatar_enabled": False}).status_code == expected
        assert other.delete(base).status_code == expected
        assert other.get(avatar["image_url"]).status_code == expected
        assert other.delete(f"{base}/{avatar['id']}").status_code == expected
        assert other.post(f"{base}/test", json={}).status_code == expected


def test_avatar_ids_are_bound_to_their_clone_and_owner(owner: TestClient, other: TestClient):
    clone_a, clone_b = ready_clone(owner), ready_clone(owner, name="Second AI")
    avatar_b = owner.get(f"/api/clones/{clone_b}/avatar").json()["active_avatar"]
    assert owner.get(f"/api/clones/{clone_a}/avatar/{avatar_b['id']}/image").status_code == 404
    assert owner.delete(f"/api/clones/{clone_a}/avatar/{avatar_b['id']}").status_code == 404
    assert owner.patch(f"/api/clones/{clone_a}/avatar", json={"active_avatar_id": avatar_b["id"]}).status_code == 404
    attacker = ready_clone(other)
    assert other.get(f"/api/clones/{attacker}/avatar/{avatar_b['id']}/image").status_code == 404
    assert other.delete(f"/api/clones/{attacker}/avatar/{avatar_b['id']}").status_code == 404


def test_video_jobs_are_private(owner: TestClient, other: TestClient):
    clone_id = ready_clone(owner, visibility="public")
    job = owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()
    status = job_of(owner, clone_id, job["job_id"])
    assert status["status"] == "completed"
    base = f"/api/clones/{clone_id}/avatar/jobs/{job['job_id']}"
    assert other.get(base).status_code == 403
    assert other.get(f"{base}/video").status_code == 403
    assert other.post(f"{base}/cancel").status_code == 403
    attacker = ready_clone(other)
    assert other.get(f"/api/clones/{attacker}/avatar/jobs/{job['job_id']}").status_code == 404
    assert other.get(f"/api/clones/{attacker}/avatar/jobs/{job['job_id']}/video").status_code == 404
    second = ready_clone(owner, name="Second AI")
    assert owner.get(f"/api/clones/{second}/avatar/jobs/{job['job_id']}").status_code == 404


def test_answer_videos_only_for_your_own_answers(owner: TestClient, other: TestClient):
    clone_id = ready_clone(owner, visibility="public")
    open_to_public(owner, clone_id)
    conversation_id, message_id = answer(owner, clone_id)
    question_id = owner.get(f"/api/conversations/{conversation_id}").json()["messages"][0]["id"]
    assert video_for(owner, clone_id, conversation_id, question_id).status_code == 404  # not an answer
    assert video_for(owner, clone_id, conversation_id, str(uuid.uuid4())).status_code == 404
    visitor_conversation, visitor_message = answer(other, clone_id)
    assert video_for(owner, clone_id, visitor_conversation, visitor_message).status_code == 404  # not theirs
    assert video_for(other, clone_id, visitor_conversation, visitor_message).status_code == 403  # not their clone
    second = ready_clone(owner, name="Second AI")
    assert video_for(owner, second, conversation_id, message_id).status_code == 404  # other clone
    bad = owner.post(f"/api/clones/{clone_id}/avatar/video", json={"audio_path": "../../etc/passwd"})
    assert bad.status_code == 400  # no paths or audio URLs are accepted


# --- Video jobs ---------------------------------------------------------------------


def test_answer_video_reuses_the_voice_reply(owner: TestClient, tts, db_session: Session):
    clone_id = ready_clone(owner)
    conversation_id, message_id = answer(owner, clone_id)
    spoken = owner.post(f"/api/conversations/{conversation_id}/messages/{message_id}/speech")
    assert spoken.status_code == 200 and len(tts.calls) == 1

    created = video_for(owner, clone_id, conversation_id, message_id)
    assert created.status_code == 202, created.text
    job = job_of(owner, clone_id, created.json()["job_id"])
    assert job["status"] == "completed" and job["progress"] == 100
    assert job["message_id"] == message_id and job["provider"] == "local"
    assert len(tts.calls) == 1  # the voice reply's audio was reused, no second TTS

    video = owner.get(job["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert video.content[4:8] == b"ftyp"
    with av.open(io.BytesIO(video.content)) as container:
        kinds = {s.type for s in container.streams}
    assert kinds == {"video", "audio"}

    stored = db_session.get(AvatarVideoJob, uuid.UUID(job["job_id"]))
    assert stored.input_audio_path and stored.output_video_path.endswith(".mp4")
    messages = owner.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert messages[1]["avatar_job_id"] == job["job_id"] and messages[1]["avatar_job_status"] == "completed"


def test_test_video_speaks_the_text(owner: TestClient, tts):
    clone_id = ready_clone(owner)
    created = owner.post(f"/api/clones/{clone_id}/avatar/test", json={"text": "Hello, I am an AI Clone."})
    assert created.status_code == 202
    assert tts.calls[-1]["text"] == "Hello, I am an AI Clone."
    assert job_of(owner, clone_id, created.json()["job_id"])["status"] == "completed"
    assert owner.post(f"/api/clones/{clone_id}/avatar/test", json={"text": " "}).status_code == 400


def test_video_requirements(owner: TestClient):
    no_voice = new_clone(owner, voice=False)
    owner.post(f"/api/clones/{no_voice}/avatar/generate", json={"preset": "ayaan"})
    owner.patch(f"/api/clones/{no_voice}/avatar", json={"avatar_enabled": True})
    response = owner.post(f"/api/clones/{no_voice}/avatar/test", json={})
    assert response.status_code == 403 and "Turn on voice" in response.json()["detail"]

    off = new_clone(owner)
    owner.post(f"/api/clones/{off}/avatar/generate", json={"preset": "ayaan"})
    response = owner.post(f"/api/clones/{off}/avatar/test", json={})
    assert response.status_code == 403 and response.json()["detail"] == "The avatar is turned off for this AI Clone."


def test_lipsync_failure_keeps_the_answer(owner: TestClient, monkeypatch):
    clone_id = ready_clone(owner)
    conversation_id, message_id = answer(owner, clone_id)

    def broken(self, request, progress):
        raise AvatarError("GPU melted with secret detail")

    monkeypatch.setattr(LocalLipSync, "render", broken)
    job = job_of(owner, clone_id, video_for(owner, clone_id, conversation_id, message_id).json()["job_id"])
    assert job["status"] == "failed" and job["video_url"] is None
    assert "text and voice answer are still available" in job["error_message"]
    assert "secret" not in job["error_message"]
    messages = owner.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert messages[1]["content"]  # the answer itself is untouched


def test_tts_failure_fails_the_job_cleanly(owner: TestClient, tts):
    clone_id = ready_clone(owner)
    tts.error = VoiceRateLimitError("quota")
    job = job_of(owner, clone_id, owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()["job_id"])
    assert job["status"] == "failed" and "free usage limit" in job["error_message"]


def test_videos_off_on_the_server(owner: TestClient, monkeypatch):
    from app.avatar.base import LipSyncNotConfiguredError

    clone_id = ready_clone(owner)

    def off():
        raise LipSyncNotConfiguredError("none")

    monkeypatch.setattr("app.avatar.factory.get_lipsync_provider", off)
    response = owner.post(f"/api/clones/{clone_id}/avatar/test", json={})
    assert response.status_code == 503
    assert owner.get(f"/api/clones/{clone_id}/avatar").json()["lipsync_provider"] is None


def test_video_rate_limit(owner: TestClient, monkeypatch):
    from app.core.config import get_settings

    clone_id = ready_clone(owner)
    monkeypatch.setattr(get_settings(), "avatar_video_rate_limit_per_minute", 2)
    assert owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).status_code == 202
    assert owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).status_code == 202
    response = owner.post(f"/api/clones/{clone_id}/avatar/test", json={})
    assert response.status_code == 429 and "avatar videos too quickly" in response.json()["detail"]


def test_cancel_a_queued_job(owner: TestClient, monkeypatch):
    clone_id = ready_clone(owner)
    monkeypatch.setattr("app.avatar.jobs.submit", lambda job_id: None)  # stays queued
    job_id = owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()["job_id"]
    assert job_of(owner, clone_id, job_id)["status"] == "queued"
    cancelled = owner.post(f"/api/clones/{clone_id}/avatar/jobs/{job_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    from app.avatar.jobs import run_job

    run_job(uuid.UUID(job_id))  # a worker picking it up later does nothing
    assert job_of(owner, clone_id, job_id)["status"] == "cancelled"


def test_interrupted_jobs_are_failed_on_startup(owner: TestClient, monkeypatch):
    from app.avatar.jobs import INTERRUPTED, recover_interrupted

    clone_id = ready_clone(owner)
    monkeypatch.setattr("app.avatar.jobs.submit", lambda job_id: None)
    job_id = owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()["job_id"]
    assert recover_interrupted() == 1
    job = job_of(owner, clone_id, job_id)
    assert job["status"] == "failed" and job["error_message"] == INTERRUPTED


def test_expired_videos_are_cleaned_up_but_avatars_stay(owner: TestClient, storage_dir):
    clone_id = ready_clone(owner)
    owner.post(f"/api/clones/{clone_id}/documents", files={"file": ("cv.txt", b"I work with Python and Django every day.", "text/plain")})
    job_id = owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()["job_id"]
    video = next((storage_dir / "clones" / clone_id / "videos").glob("*.mp4"))
    old = time.time() - 25 * 3600
    os.utime(video, (old, old))

    job = job_of(owner, clone_id, job_id)
    assert job["status"] == "completed" and job["expired"] and job["video_url"] is None
    assert owner.get(f"/api/clones/{clone_id}/avatar/jobs/{job_id}/video").status_code == 404
    assert get_avatar_storage().cleanup_videos() == 1
    assert not video.exists()
    assert len(list((storage_dir / "clones" / clone_id / "avatar").glob("*.png"))) == 1
    assert len(list((storage_dir / "clones" / clone_id / "documents").iterdir())) == 1


def test_deleting_the_clone_removes_avatars_jobs_and_files(owner: TestClient, db_session: Session, storage_dir):
    clone_id = ready_clone(owner)
    owner.post(f"/api/clones/{clone_id}/avatar/test", json={})
    assert owner.delete(f"/api/clones/{clone_id}").status_code == 204
    assert db_session.scalars(select(CloneAvatar)).all() == []
    assert db_session.scalars(select(AvatarVideoJob)).all() == []
    assert not (storage_dir / "clones" / clone_id).exists()


def test_turning_the_avatar_off_keeps_text_and_voice(owner: TestClient):
    clone_id = ready_clone(owner)
    owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_enabled": False})
    assert owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).status_code == 403
    conversation_id, message_id = answer(owner, clone_id)
    assert owner.post(f"/api/conversations/{conversation_id}/messages/{message_id}/speech").status_code == 200
    assert owner.get(f"/api/clones/{clone_id}/chat-profile").json()["avatar_enabled"] is False


# --- Providers ----------------------------------------------------------------------


def _render_local(tmp_path, seconds: float = 1.0):
    from app.avatar.providers.illustrated import PRESETS, IllustratedAvatarProvider

    avatar = IllustratedAvatarProvider().generate(PRESETS["ayaan"])
    image, audio, out = tmp_path / "a.png", tmp_path / "a.wav", tmp_path / "a.mp4"
    image.write_bytes(avatar.png)
    audio.write_bytes(tone_wav(seconds, 24_000))
    request = LipSyncRequest(image, audio, out, avatar.mouth, True, max_seconds=60, fps=25)
    return request, avatar


def test_local_lipsync_moves_the_mouth_with_the_sound(tmp_path):
    request, avatar = _render_local(tmp_path)
    progress: list[int] = []
    duration = LocalLipSync().render(request, progress.append)
    assert 0.9 <= duration <= 1.1 and progress[-1] == 95
    with av.open(str(request.output_path)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    mouth_y, mouth_x = int(avatar.mouth.y * avatar.height), int(avatar.mouth.x * avatar.width)
    patch = lambda f: f[mouth_y : mouth_y + 20, mouth_x - 15 : mouth_x + 15].astype(int)  # noqa: E731
    assert abs(patch(frames[len(frames) // 2]) - patch(frames[0])).mean() > 10  # open mid-tone vs closed start


def test_mouth_stays_closed_in_silence_and_opens_for_speech():
    import numpy as np

    assert float(mouth_envelope(np.zeros(24_000, dtype="int16"), 25).max()) == 0.0
    hiss = (np.random.default_rng(1).normal(0, 20, 24_000)).astype("int16")  # faint background noise
    assert float(mouth_envelope(hiss, 25).max()) == 0.0
    speech = np.concatenate([np.zeros(12_000), 8000 * np.sin(np.arange(12_000) / 5)]).astype("int16")
    opening = mouth_envelope(speech, 25)
    assert opening[:10].max() == 0.0 and opening[-5:].min() > 0.5  # shut, then open when the sound starts


def test_video_length_is_capped(tmp_path):
    request, _ = _render_local(tmp_path, seconds=3.0)
    capped = LipSyncRequest(**{**request.__dict__, "max_seconds": 1.0})
    assert LocalLipSync().render(capped, lambda p: None) <= 1.05


def test_http_lipsync_provider(tmp_path):
    request, _ = _render_local(tmp_path)
    LocalLipSync().render(request, lambda p: None)
    mp4 = request.output_path.read_bytes()
    seen: dict = {}

    def server(http_request: httpx.Request) -> httpx.Response:
        seen["auth"] = http_request.headers.get("authorization")
        seen["body"] = http_request.content
        return httpx.Response(200, content=mp4, headers={"content-type": "video/mp4"})

    out = tmp_path / "remote.mp4"
    remote = LipSyncRequest(**{**request.__dict__, "output_path": out})
    provider = HttpLipSync("http://lipsync.local/render", "secret-key", 30, transport=httpx.MockTransport(server))
    assert provider.render(remote, lambda p: None) > 0.5
    assert seen["auth"] == "Bearer secret-key" and b'name="image"' in seen["body"] and b'name="audio"' in seen["body"]

    from app.avatar.base import LipSyncUnavailableError

    busy = HttpLipSync("http://x", None, 30, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(LipSyncUnavailableError):
        busy.render(remote, lambda p: None)
    junk = HttpLipSync("http://x", None, 30, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"nope")))
    with pytest.raises(AvatarError):
        junk.render(remote, lambda p: None)


def test_default_mouth_when_no_face(owner: TestClient):
    clone_id = new_clone(owner)
    avatar = upload(owner, clone_id).json()  # a plain coloured image: no face
    assert avatar["face_detected"] is False
    assert avatar["error_message"] == "No face was found. Set the mouth position by hand."
    assert MouthPosition(avatar["mouth_x"], avatar["mouth_y"], avatar["mouth_width"]).x == 0.5


def test_jobs_run_speech_on_the_app_event_loop(owner: TestClient, tts):
    """Async provider clients are bound to the loop they first ran on (like the Gemini
    client): every job must use the app's loop, not a new asyncio.run() loop."""
    import asyncio
    import threading

    from app.avatar import jobs

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    seen: list[asyncio.AbstractEventLoop] = []
    original = tts.synthesize

    async def loop_bound(text, voice, language=None):
        current = asyncio.get_running_loop()
        if seen and current is not seen[0]:
            raise RuntimeError("Event loop is closed")  # what a real shared client does
        seen.append(current)
        return await original(text, voice, language)

    tts.synthesize = loop_bound
    jobs.set_event_loop(loop)
    try:
        clone_id = ready_clone(owner)
        for text in ("First video.", "Second video."):
            job_id = owner.post(f"/api/clones/{clone_id}/avatar/test", json={"text": text}).json()["job_id"]
            assert job_of(owner, clone_id, job_id)["status"] == "completed"
        assert len(seen) == 2 and all(found is loop for found in seen)
    finally:
        jobs.set_event_loop(None)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


def test_protected_media_is_never_cached_by_the_browser(owner: TestClient):
    """On a shared computer, a cached copy would reach the next user without any server check."""
    clone_id = ready_clone(owner)
    avatar = owner.get(f"/api/clones/{clone_id}/avatar").json()["active_avatar"]
    job = job_of(owner, clone_id, owner.post(f"/api/clones/{clone_id}/avatar/test", json={}).json()["job_id"])
    conversation_id, message_id = answer(owner, clone_id)
    audio = owner.post(f"/api/conversations/{conversation_id}/messages/{message_id}/speech").json()["audio_url"]
    for url in (avatar["image_url"], job["video_url"], audio):
        response = owner.get(url)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def _fal_server(mp4: bytes, seen: dict, states=("IN_QUEUE", "IN_PROGRESS", "COMPLETED")):
    """A fake fal.ai queue: submit -> status (several polls) -> result -> CDN download."""
    import json

    polls = iter(states)

    def server(http_request: httpx.Request) -> httpx.Response:
        url = str(http_request.url)
        seen.setdefault("calls", []).append((http_request.method, url))
        if http_request.method == "POST":
            seen["auth"] = http_request.headers.get("authorization")
            seen["payload"] = json.loads(http_request.content)
            base = "https://queue.fal.run/veed/fabric-1.0/requests/r1"
            return httpx.Response(
                200, json={"request_id": "r1", "status_url": f"{base}/status", "response_url": base, "cancel_url": f"{base}/cancel"}
            )
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": next(polls)})
        if url.endswith("/cancel"):
            seen["cancelled"] = True
            return httpx.Response(202)
        if url.startswith("https://queue.fal.run"):
            return httpx.Response(200, json={"video": {"url": "https://v3.fal.media/files/out.mp4"}})
        seen["download_auth"] = http_request.headers.get("authorization")
        return httpx.Response(200, content=mp4)

    return server


def test_fal_lipsync_provider(tmp_path):
    from app.avatar.providers.fal_lipsync import FalLipSync

    request, _ = _render_local(tmp_path)
    LocalLipSync().render(request, lambda p: None)
    mp4 = request.output_path.read_bytes()
    seen: dict = {}
    out = tmp_path / "fal.mp4"
    remote = LipSyncRequest(**{**request.__dict__, "output_path": out})
    progress: list[int] = []
    provider = FalLipSync("fal-secret", "veed/fabric-1.0", "480p", 30, poll_seconds=0, transport=httpx.MockTransport(_fal_server(mp4, seen)))
    assert provider.render(remote, progress.append) > 0.5
    assert seen["auth"] == "Key fal-secret"
    payload = seen["payload"]
    assert payload["image_url"].startswith("data:image/jpeg;base64,")
    assert payload["audio_url"].startswith("data:audio/mpeg;base64,")
    assert payload["resolution"] == "480p"
    assert seen["download_auth"] is None  # the key never goes to the CDN
    assert "cancelled" not in seen and progress == sorted(progress)
    assert out.read_bytes()[4:8] == b"ftyp"


def test_fal_lipsync_errors(tmp_path):
    from app.avatar.base import LipSyncNotConfiguredError, LipSyncTimeoutError, LipSyncUnavailableError
    from app.avatar.providers.fal_lipsync import FalLipSync

    request, _ = _render_local(tmp_path)
    remote = LipSyncRequest(**{**request.__dict__, "output_path": tmp_path / "x.mp4"})

    def fixed(code):
        return httpx.MockTransport(lambda r: httpx.Response(code, json={"detail": "x"}))

    with pytest.raises(LipSyncNotConfiguredError):
        FalLipSync(None, "veed/fabric-1.0", "480p", 30).render(remote, lambda p: None)
    with pytest.raises(LipSyncNotConfiguredError):
        FalLipSync("k", "someone/unknown-model", "480p", 30).render(remote, lambda p: None)
    with pytest.raises(LipSyncNotConfiguredError):
        FalLipSync("bad", "veed/fabric-1.0", "480p", 30, transport=fixed(401)).render(remote, lambda p: None)
    for code in (402, 429, 503):
        with pytest.raises(LipSyncUnavailableError):
            FalLipSync("k", "veed/fabric-1.0", "480p", 30, transport=fixed(code)).render(remote, lambda p: None)

    # Gives up after the timeout and cancels the paid request.
    seen: dict = {}
    slow = FalLipSync(
        "k", "veed/fabric-1.0", "480p", 0, poll_seconds=0,
        transport=httpx.MockTransport(_fal_server(b"", seen, states=["IN_PROGRESS"] * 50)),
    )
    with pytest.raises(LipSyncTimeoutError):
        slow.render(remote, lambda p: None)
    assert seen.get("cancelled") is True and not remote.output_path.exists()

    # A non-MP4 "video" is rejected.
    junk = FalLipSync("k", "veed/fabric-1.0", "480p", 30, poll_seconds=0, transport=httpx.MockTransport(_fal_server(b"not a video", {})))
    with pytest.raises(AvatarError):
        junk.render(remote, lambda p: None)
    assert not remote.output_path.exists()


def test_fal_sadtalker_uses_its_field_names(tmp_path):
    from app.avatar.providers.fal_lipsync import FalLipSync

    request, _ = _render_local(tmp_path)
    LocalLipSync().render(request, lambda p: None)
    seen: dict = {}
    remote = LipSyncRequest(**{**request.__dict__, "output_path": tmp_path / "s.mp4"})
    FalLipSync("k", "fal-ai/sadtalker", "480p", 30, poll_seconds=0, transport=httpx.MockTransport(_fal_server(request.output_path.read_bytes(), seen))).render(remote, lambda p: None)
    assert "source_image_url" in seen["payload"] and "driven_audio_url" in seen["payload"] and "resolution" not in seen["payload"]
