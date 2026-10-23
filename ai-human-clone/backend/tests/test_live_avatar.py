"""Live video calls (Simli). Simli itself is a mock transport here."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.avatar import live_avatar
from app.core.config import get_settings
from app.models import CloneProfile, UsageEvent
from tests.conftest import open_to_public
from tests.test_avatar import new_clone, other, owner, ready_clone, upload  # noqa: F401 - fixtures


class FakeSimli:
    def __init__(self, face_state: str = "completed") -> None:
        self.calls: list[tuple[str, str]] = []
        self.keys: set[str | None] = set()
        self.face_state = face_state
        self.token_body: dict | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        self.keys.add(request.headers.get("x-simli-api-key"))
        if path == "/faces/trinity":
            assert b'name="image"' in request.content
            return httpx.Response(200, json={"face_id": "face-123"})
        if path == "/faces/trinity/generation_status":
            return httpx.Response(200, json={"status": self.face_state})
        if path == "/compose/token":
            self.token_body = json.loads(request.content)
            return httpx.Response(200, json={"session_token": "sess-abc"})
        if path == "/compose/ice":
            return httpx.Response(200, json=[{"urls": ["turn:turn.example:3478"], "username": "u", "credential": "c"}])
        return httpx.Response(404)


@pytest.fixture
def simli(monkeypatch) -> FakeSimli:
    fake = FakeSimli()
    monkeypatch.setattr(get_settings(), "simli_api_key", "simli-secret")
    monkeypatch.setattr(live_avatar, "_transport", httpx.MockTransport(fake))
    live_avatar.reset_limits()
    return fake


def _with_face(client: TestClient) -> str:
    clone_id = ready_clone(client)
    response = client.post(f"/api/clones/{clone_id}/live-avatar/face")
    assert response.status_code == 200, response.text
    return clone_id


def test_off_without_key(owner: TestClient) -> None:
    clone_id = ready_clone(owner)
    status = owner.get(f"/api/clones/{clone_id}/live-avatar").json()
    assert status["available"] is False
    assert owner.get(f"/api/clones/{clone_id}/live-call").json()["can_call"] is False
    assert owner.post(f"/api/clones/{clone_id}/live-call").status_code == 503


def test_face_creation_and_call(owner: TestClient, simli: FakeSimli, db_session: Session) -> None:
    clone_id = _with_face(owner)
    status = owner.get(f"/api/clones/{clone_id}/live-avatar").json()
    assert status["face_ready"] is True and status["face_status"] == "ready"
    assert "face-123" not in json.dumps(status)  # the page doesn't need the id

    assert owner.get(f"/api/clones/{clone_id}/live-call").json() == {"can_call": True, "reason": None}
    call = owner.post(f"/api/clones/{clone_id}/live-call")
    assert call.status_code == 201
    body = call.json()
    assert body["session_token"] == "sess-abc" and body["ice_servers"][0]["urls"] == ["turn:turn.example:3478"]
    assert "simli-secret" not in call.text  # the key stays on the server
    assert simli.keys == {"simli-secret"}
    assert simli.token_body["faceId"] == "face-123" and simli.token_body["handleSilence"] is True
    assert simli.token_body["maxSessionLength"] == get_settings().live_call_max_minutes * 60

    assert owner.post(f"/api/clones/{clone_id}/live-call/end", json={"seconds": 90}).status_code == 204
    db_session.expire_all()
    usage = db_session.scalar(select(UsageEvent).where(UsageEvent.event_type == "LIVE_CALL"))
    assert usage.output_units == 1.5 and usage.provider == "simli"


def test_face_still_processing(owner: TestClient, simli: FakeSimli) -> None:
    simli.face_state = "processing"
    clone_id = _with_face(owner)
    status = owner.get(f"/api/clones/{clone_id}/live-avatar").json()
    assert status["face_status"] == "processing" and status["face_ready"] is False
    assert owner.post(f"/api/clones/{clone_id}/live-call").status_code == 403
    simli.face_state = "completed"
    assert owner.get(f"/api/clones/{clone_id}/live-avatar").json()["face_ready"] is True


def test_failed_face(owner: TestClient, simli: FakeSimli) -> None:
    simli.face_state = "failed"
    clone_id = _with_face(owner)
    status = owner.get(f"/api/clones/{clone_id}/live-avatar").json()
    assert status["face_status"] == "failed" and status["face_error"]


def test_manual_face_id(owner: TestClient, simli: FakeSimli) -> None:
    clone_id = ready_clone(owner)
    assert owner.put(f"/api/clones/{clone_id}/live-avatar/face-id", json={"face_id": "bad id!"}).status_code == 400
    response = owner.put(f"/api/clones/{clone_id}/live-avatar/face-id", json={"face_id": "my-simli-face-1"})
    assert response.json()["face_ready"] is True
    owner.post(f"/api/clones/{clone_id}/live-call")
    assert simli.token_body["faceId"] == "my-simli-face-1"


def test_new_photo_or_withdrawn_consent_resets_face(owner: TestClient, simli: FakeSimli, db_session: Session) -> None:
    clone_id = _with_face(owner)
    assert upload(owner, clone_id).status_code == 201
    assert owner.get(f"/api/clones/{clone_id}/live-avatar").json()["face_status"] == "none"

    owner.post(f"/api/clones/{clone_id}/live-avatar/face")
    owner.patch(f"/api/clones/{clone_id}/avatar", json={"avatar_consent_given": False})
    db_session.expire_all()
    clone = db_session.scalar(select(CloneProfile))
    assert clone.live_face_id is None and clone.live_face_status == "none"


def test_call_needs_avatar_voice_and_face(owner: TestClient, simli: FakeSimli) -> None:
    clone_id = new_clone(owner, consent=False)
    assert owner.post(f"/api/clones/{clone_id}/live-avatar/face").status_code == 403
    reason = owner.get(f"/api/clones/{clone_id}/live-call").json()["reason"]
    assert "avatar" in reason.lower()


def test_other_users(owner: TestClient, other: TestClient, simli: FakeSimli) -> None:
    clone_id = _with_face(owner)
    # Private clone: not found, and only the owner manages the face.
    assert other.post(f"/api/clones/{clone_id}/live-call").status_code == 404
    assert other.post(f"/api/clones/{clone_id}/live-avatar/face").status_code == 404
    open_to_public(owner, clone_id, voice=True)
    assert other.post(f"/api/clones/{clone_id}/live-call").status_code == 403  # public avatars still off
    owner.patch(f"/api/clones/{clone_id}/public-settings", json={"public_avatar_enabled": True})
    assert other.post(f"/api/clones/{clone_id}/live-call").status_code == 201
    assert other.post(f"/api/clones/{clone_id}/live-avatar/face").status_code == 403


def test_call_rate_limit(owner: TestClient, simli: FakeSimli, monkeypatch) -> None:
    clone_id = _with_face(owner)
    monkeypatch.setattr(get_settings(), "live_call_rate_limit_per_minute", 2)
    codes = [owner.post(f"/api/clones/{clone_id}/live-call").status_code for _ in range(3)]
    assert codes == [201, 201, 429]


def test_simli_errors_are_safe(owner: TestClient, simli: FakeSimli, monkeypatch) -> None:
    clone_id = _with_face(owner)
    monkeypatch.setattr(live_avatar, "_transport", httpx.MockTransport(lambda r: httpx.Response(401)))
    response = owner.post(f"/api/clones/{clone_id}/live-call")
    assert response.status_code == 503 and "simli-secret" not in response.text
    monkeypatch.setattr(live_avatar, "_transport", httpx.MockTransport(lambda r: httpx.Response(502)))
    assert owner.post(f"/api/clones/{clone_id}/live-call").status_code == 503
