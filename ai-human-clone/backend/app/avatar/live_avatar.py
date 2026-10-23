"""Live video call with the clone's avatar, streamed by Simli (https://simli.com).

How it works:
1. Live face. Once, the owner turns the active avatar photo into a Simli "face"
   (POST /faces/trinity, takes from minutes up to a few hours), or pastes the id
   of a face made in the Simli app. The photo is sent to Simli only for this.
2. Call. The browser asks this API for a call; we create a short-lived Simli
   session token and ICE servers with the server-side SIMLI_API_KEY (the key
   never reaches the browser) and return them. The browser connects to Simli
   over WebRTC: the face idles naturally (blinks, small head moves) and, when it
   is sent the answer's speech, lip-syncs it in real time.
3. Each turn is the normal voice chat (speech to text, RAG answer, the clone's
   TTS voice); the browser then streams that speech to the live face.

Calls are capped (LIVE_CALL_MAX_MINUTES, LIVE_CALL_MAX_IDLE_SECONDS) and rate
limited. When a call ends the browser reports its length, recorded as usage
(LIVE_CALL, minutes, capped at the maximum).
"""

import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.avatar import avatar_service
from app.avatar.base import AvatarError, LipSyncNotConfiguredError, LipSyncUnavailableError
from app.core.config import get_settings
from app.models import CloneProfile, User
from app.services import monitoring
from app.services.errors import ForbiddenError, InvalidInputError
from app.services.rate_limit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "Live video calls aren't set up on this server (SIMLI_API_KEY)."
NEEDS_AVATAR = "Add an avatar photo and give avatar consent first."
NEEDS_VOICE = "Turn on the clone's voice first: the live avatar speaks with it."
FACE_NOT_READY = "The live face isn't ready yet."
CALLS_OFF = "Live video calls aren't available for this AI Clone."
_FACE_ID = re.compile(r"^[A-Za-z0-9_\-:.]{4,100}$")
_READY = {"completed", "complete", "done", "ready", "success", "succeeded", "finished"}
_FAILED = {"failed", "error", "errored", "rejected", "cancelled", "canceled"}

call_limiter = SlidingWindowLimiter()


@dataclass(frozen=True)
class LiveCall:
    session_token: str
    ice_servers: list[dict]
    max_seconds: int
    max_idle_seconds: int


def configured() -> bool:
    return bool(get_settings().simli_api_key)


def _client(timeout: float = 30.0, transport=None) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.simli_api_url.rstrip("/"),
        headers={"x-simli-api-key": settings.simli_api_key or ""},
        timeout=timeout,
        transport=transport or _transport,
    )


_transport = None  # tests set a mock transport


def _check(response: httpx.Response, what: str) -> None:
    code = response.status_code
    if code in (401, 403):
        raise LipSyncNotConfiguredError(f"Simli rejected the API key ({code})")
    if code == 402:
        raise LipSyncUnavailableError("Simli account has no minutes or credit left (402)")
    if code == 429 or code >= 500:
        raise LipSyncUnavailableError(f"Simli {what} returned {code}")
    if code >= 400:
        error = AvatarError(f"Simli {what} returned {code}: {response.text[:300]}")
        error.user_message = "The live avatar service couldn't use this photo. Try a clear, front-facing photo."
        error.status_code = 400
        raise error


def _require_configured() -> None:
    if not configured():
        raise LipSyncNotConfiguredError(NOT_CONFIGURED)


def _first(data: object, *keys: str) -> str | None:
    """Find the first non-empty value for any of `keys`, also one level down."""
    if isinstance(data, dict):
        for key in keys:
            if data.get(key):
                return str(data[key])
        for value in data.values():
            found = _first(value, *keys) if isinstance(value, dict) else None
            if found:
                return found
    return None


# --- Live face --------------------------------------------------------------------


def status_of(clone: CloneProfile) -> dict:
    return {
        "available": configured(),
        "face_status": clone.live_face_status,
        "face_ready": clone.live_face_status == "ready" and bool(clone.live_face_id),
        "face_error": clone.live_face_error,
        "max_minutes": get_settings().live_call_max_minutes,
    }


def reset_face(clone: CloneProfile) -> None:
    """The photo changed or consent was withdrawn: the old live face no longer applies."""
    clone.live_face_id = None
    clone.live_face_status = "none"
    clone.live_face_error = None


def create_face(db: Session, clone: CloneProfile) -> dict:
    """Send the active avatar photo to Simli to build the live face."""
    _require_configured()
    avatar = avatar_service.active_avatar(db, clone)
    if not clone.avatar_consent_given or avatar is None or avatar.status != "ready":
        raise ForbiddenError(NEEDS_AVATAR)
    image = avatar_service.image_path(avatar).read_bytes()
    try:
        with _client(timeout=120.0) as client:
            response = client.post(
                "/faces/trinity",
                params={"face_name": f"clone-{clone.slug}"[:60]},
                files={"image": ("avatar.png", image, "image/png")},
            )
    except httpx.HTTPError as exc:
        raise LipSyncUnavailableError("Could not reach Simli") from exc
    _check(response, "face creation")
    body = response.json() if response.content else {}
    face_id = _first(body, "face_id", "faceId", "character_uid", "id")
    if not face_id:
        raise AvatarError(f"Simli didn't return a face id: {str(body)[:200]}")
    clone.live_face_id = face_id[:100]
    clone.live_face_status = "processing"
    clone.live_face_error = None
    db.commit()
    logger.info("Simli live face requested for clone %s", clone.id)
    return refresh_face(db, clone)


def refresh_face(db: Session, clone: CloneProfile) -> dict:
    """Ask Simli whether a processing face is ready."""
    if clone.live_face_status != "processing" or not clone.live_face_id or not configured():
        return status_of(clone)
    try:
        with _client() as client:
            response = client.get("/faces/trinity/generation_status", params={"face_id": clone.live_face_id})
    except httpx.HTTPError:
        return status_of(clone)  # try again later
    if response.status_code >= 400:
        logger.warning("Simli face status returned %s", response.status_code)
        return status_of(clone)
    body = response.json() if response.content else {}
    state = (_first(body, "status", "state") or "").lower()
    if state in _READY:
        clone.live_face_status = "ready"
        clone.live_face_id = _first(body, "face_id", "faceId", "character_uid") or clone.live_face_id
    elif state in _FAILED:
        clone.live_face_status = "failed"
        clone.live_face_error = (_first(body, "error", "message", "detail") or "Simli couldn't build a face from this photo.")[:300]
    db.commit()
    return status_of(clone)


def set_face_id(db: Session, clone: CloneProfile, face_id: str) -> dict:
    """Use a face made in the Simli app (app.simli.com) instead."""
    face_id = face_id.strip()
    if not _FACE_ID.match(face_id):
        raise InvalidInputError("That doesn't look like a Simli face id.")
    if not clone.avatar_consent_given:
        raise ForbiddenError(NEEDS_AVATAR)
    clone.live_face_id = face_id
    clone.live_face_status = "ready"
    clone.live_face_error = None
    db.commit()
    return status_of(clone)


# --- Calls ------------------------------------------------------------------------


def call_problem(clone: CloneProfile, user: User) -> str | None:
    """Why `user` can't video-call this clone right now (None = they can)."""
    if not configured():
        return NOT_CONFIGURED
    is_owner = clone.owner_id == user.id
    if not clone.avatar_enabled or not clone.avatar_consent_given:
        return NEEDS_AVATAR if is_owner else CALLS_OFF
    if not is_owner and not clone.public_avatar_enabled:
        return CALLS_OFF
    if not (clone.voice_enabled and clone.voice_consent_given):
        return NEEDS_VOICE if is_owner else CALLS_OFF
    if clone.live_face_status != "ready" or not clone.live_face_id:
        return FACE_NOT_READY if is_owner else CALLS_OFF
    return None


def start_call(clone: CloneProfile, user: User) -> LiveCall:
    """A short-lived Simli session for this browser. Owner, or a user allowed to chat
    with the clone when its owner made avatars public."""
    _require_configured()
    problem = call_problem(clone, user)
    if problem:
        raise ForbiddenError(problem)
    settings = get_settings()
    call_limiter.check(
        str(user.id), settings.live_call_rate_limit_per_minute, "You're starting calls too quickly. Please wait a moment."
    )
    max_seconds = settings.live_call_max_minutes * 60
    try:
        with _client() as client:
            token = client.post(
                "/compose/token",
                json={
                    "faceId": clone.live_face_id,
                    "apiVersion": "v2",
                    "handleSilence": True,  # natural idle motion between answers
                    "maxSessionLength": max_seconds,
                    "maxIdleTime": settings.live_call_max_idle_seconds,
                },
            )
            _check(token, "session")
            ice = client.get("/compose/ice")
    except httpx.HTTPError as exc:
        raise LipSyncUnavailableError("Could not reach Simli") from exc
    session_token = _first(token.json(), "session_token", "sessionToken", "token")
    if not session_token:
        raise AvatarError("Simli didn't return a session token")
    ice_servers = ice.json() if ice.status_code == 200 else []
    if not isinstance(ice_servers, list) or not ice_servers:
        ice_servers = [{"urls": ["stun:stun.l.google.com:19302"]}]
    logger.info("Live call started for clone %s", clone.id)
    return LiveCall(
        session_token=session_token,
        ice_servers=ice_servers,
        max_seconds=max_seconds,
        max_idle_seconds=settings.live_call_max_idle_seconds,
    )


def record_call_end(clone: CloneProfile, user: User, seconds: float) -> None:
    """Usage only: call length in minutes (as reported by the browser, capped)."""
    capped = min(max(seconds, 0.0), get_settings().live_call_max_minutes * 60)
    monitoring.usage(
        "LIVE_CALL",
        provider="simli",
        user_id=user.id,
        clone_id=clone.id,
        output_units=round(capped / 60, 2),
        duration_ms=int(capped * 1000),
    )


def reset_limits() -> None:
    call_limiter.reset()
