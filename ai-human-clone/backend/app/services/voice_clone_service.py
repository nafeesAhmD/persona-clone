"""The owner's personal voice clone (ElevenLabs Instant Voice Cloning, or the free
self-hosted Chatterbox service; VOICE_CLONE_PROVIDER picks one, see app/voice/routing.py).

Rules:
- Owner only (routes use clone_service.get_managed_clone).
- Consent twice: the clone's voice consent (voice_consent_given) AND an explicit
  clone consent with the recordings ("this is my own voice, or I have the
  speaker's permission").
- Recordings are validated, sent to the provider once and never stored here; only
  the provider's voice id is kept, prefixed with the provider ("local:<hex>",
  "elevenlabs:<id>"; old unprefixed ids are ElevenLabs).
- Creating a new cloned voice replaces (and deletes) the previous one.
- Deleting the cloned voice, withdrawing voice consent or deleting the clone
  deletes the voice at the provider that made it (best effort: a provider outage never blocks
  the local delete; it is logged so the voice can be removed by hand).
- The cloned voice is used for all speech (see app/voice/routing.py) while
  use_cloned_voice is on; turning it off falls back to the prebuilt voice.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CloneProfile, PendingVoiceDeletion
from app.schemas.voice import VoiceCloneStatus
from app.services.errors import ForbiddenError, InvalidInputError
from app.services.rate_limit import SlidingWindowLimiter
from app.voice import routing
from app.voice.audio import validate_and_normalise
from app.voice.base import VoiceError
from app.voice.providers import local_clone

logger = logging.getLogger(__name__)

VOICE_CONSENT_REQUIRED = "Give voice consent for this AI Clone before creating a cloned voice."
CLONE_CONSENT_REQUIRED = (
    "Please confirm this is your own voice, or that you have the speaker's permission to clone it."
)
NOT_READY = "Create your cloned voice first."
CLONE_FAILED = "The voice couldn't be cloned. Please try again."

# Cloning is slow and costly: a few attempts per user per hour.
clone_limiter = SlidingWindowLimiter(window_seconds=3600.0)
CLONE_ATTEMPTS_PER_HOUR = 3


def status_of(clone: CloneProfile) -> VoiceCloneStatus:
    settings = get_settings()
    active = routing.active_provider()
    # The provider of the existing voice; otherwise the one new recordings would go to.
    provider = routing.provider_of(clone.voice_clone_id) or active
    return VoiceCloneStatus(
        available=active is not None,
        status=clone.voice_clone_status or "none",
        error=clone.voice_clone_error,
        use_cloned_voice=bool(clone.use_cloned_voice),
        consent_at=clone.voice_clone_consent_at,
        provider=provider,
        min_seconds=settings.voice_clone_min_seconds,
        max_seconds=settings.voice_clone_max_seconds,
        max_files=settings.voice_clone_max_files,
        model=local_clone.MODEL if provider == local_clone.NAME else settings.elevenlabs_model,
    )


def require_available() -> None:
    """503 with a clear message when no voice clone provider is set up."""
    routing.clone_provider()


def _check_files(
    files: list[tuple[str | None, bytes, str | None]], *, as_wav: bool = False
) -> list[tuple[str, bytes, str]]:
    """Validate every sample (type, size, real audio) and the total length. Raises 400s.

    Returns the original recordings (best quality for ElevenLabs), or with `as_wav` the
    validated 16 kHz mono WAV of each (what the local service wants)."""
    settings = get_settings()
    if not files:
        raise InvalidInputError("Add at least one recording of your voice.")
    if len(files) > settings.voice_clone_max_files:
        raise InvalidInputError(f"Use at most {settings.voice_clone_max_files} recordings.")
    total = 0.0
    checked = []
    for index, (filename, data, content_type) in enumerate(files, start=1):
        clip = validate_and_normalise(data, filename, content_type, max_seconds=settings.voice_clone_max_seconds)
        total += clip.duration_seconds
        mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        if as_wav:
            checked.append((f"sample-{index}.wav", clip.wav, "audio/wav"))
        else:
            checked.append((filename or f"sample-{index}", data, mime))  # the original: best quality to clone
    if total < settings.voice_clone_min_seconds:
        raise InvalidInputError(
            f"The recordings are too short. Record at least {settings.voice_clone_min_seconds:g} seconds "
            f"in total (you have {int(total)}). 1–2 minutes works best."
        )
    if total > settings.voice_clone_max_seconds:
        raise InvalidInputError(
            f"The recordings are too long. Use at most {settings.voice_clone_max_seconds:g} seconds "
            f"in total (you have {round(total)})."
        )
    return checked


def delete_at_provider(voice_clone_id: str | None, clone_id: object) -> bool:
    """Delete a cloned voice at the provider that made it (from the id's prefix, even if
    VOICE_CLONE_PROVIDER changed since). Never raises; returns whether it worked.

    Call it after the database change is committed. If the provider (or one of the local
    services, such as a Colab GPU that is off) could not delete it, the voice is kept in
    pending_voice_deletions and retried hourly until it is gone everywhere. The voice id
    is logged too (not secret: using it needs the API key or the service).
    """
    if not voice_clone_id:
        return True
    error = _try_delete(voice_clone_id)
    if error is None:
        return True
    logger.warning(
        "Could not delete cloned voice %s of clone %s (%s); it will be retried hourly",
        voice_clone_id, clone_id, error,
    )
    _keep_pending(voice_clone_id, error)
    return False


def _try_delete(voice_clone_id: str) -> str | None:
    """Delete the voice at its provider; returns None if it worked, else a short reason."""
    provider, voice_id = routing.split(voice_clone_id)
    if not routing.provider_configured(provider):
        return f"the {provider} provider is not set up"
    try:
        routing.clone_provider(provider).delete_voice(voice_id)
        return None
    except VoiceError as exc:
        return f"{type(exc).__name__}: {exc}"[:200]
    except Exception as exc:  # noqa: BLE001 - never block a delete on the provider
        return type(exc).__name__


def _keep_pending(voice_clone_id: str, error: str) -> None:
    try:
        with SessionLocal() as db:
            if db.scalar(select(PendingVoiceDeletion).where(PendingVoiceDeletion.voice_clone_id == voice_clone_id)):
                return
            db.add(PendingVoiceDeletion(voice_clone_id=voice_clone_id, attempts=1, last_error=error,
                                        last_attempt_at=datetime.now(UTC)))
            db.commit()
    except Exception as exc:  # noqa: BLE001 - the warning above already names the voice
        logger.warning("Could not record pending voice deletion %s (%s)", voice_clone_id, type(exc).__name__)


def retry_pending_deletions() -> int:
    """Try every pending voice deletion again (hourly, see app/voice/cleanup.py).
    Returns how many voices are now deleted everywhere."""
    done = 0
    with SessionLocal() as db:
        for pending in db.scalars(select(PendingVoiceDeletion).order_by(PendingVoiceDeletion.created_at)).all():
            error = _try_delete(pending.voice_clone_id)
            if error is None:
                db.delete(pending)
                done += 1
                logger.info("Deleted pending cloned voice %s", pending.voice_clone_id)
            else:
                pending.attempts += 1
                pending.last_error = error
                pending.last_attempt_at = datetime.now(UTC)
            db.commit()
    return done


def detach(clone: CloneProfile) -> str | None:
    """Clear the cloned voice on the clone (no commit). Returns the provider voice id to
    pass to delete_at_provider once the change is committed."""
    voice_clone_id = clone.voice_clone_id
    _clear(clone)
    return voice_clone_id


def _clear(clone: CloneProfile) -> None:
    clone.voice_clone_id = None
    clone.voice_clone_status = "none"
    clone.voice_clone_error = None
    clone.voice_clone_consent_at = None
    clone.use_cloned_voice = False


async def create_clone(
    db: Session,
    clone: CloneProfile,
    files: list[tuple[str | None, bytes, str | None]],
    *,
    consent: bool,
    remove_background_noise: bool = False,
) -> VoiceCloneStatus:
    """Clone the owner's voice from `files` [(filename, bytes, content_type)]."""
    name = routing.active_provider()
    provider = routing.clone_provider(name)  # 503 when no provider is set up
    if not clone.voice_consent_given:
        raise ForbiddenError(VOICE_CONSENT_REQUIRED)
    if not consent:
        raise InvalidInputError(CLONE_CONSENT_REQUIRED)
    checked = await run_in_threadpool(lambda: _check_files(files, as_wav=name == local_clone.NAME))
    clone_limiter.check(str(clone.owner_id), CLONE_ATTEMPTS_PER_HOUR,
                        "You've tried to clone your voice several times. Please wait an hour and try again.")

    previous = clone.voice_clone_id
    clone.voice_clone_status, clone.voice_clone_error = "processing", None
    await run_in_threadpool(db.commit)
    try:
        voice_clone_id = await provider.clone_voice(f"{clone.name} (AI Clone)", checked, remove_background_noise)
    except Exception as exc:  # noqa: BLE001 - reported as status "failed" with a safe message
        logger.warning("Voice cloning failed for clone %s (%s: %s)", clone.id, type(exc).__name__,
                       exc if isinstance(exc, VoiceError) else "unexpected error")
        # A previous working voice stays usable ("ready"); otherwise the clone shows "failed".
        clone.voice_clone_status = "ready" if previous else "failed"
        clone.voice_clone_error = (exc.user_message if isinstance(exc, VoiceError) else CLONE_FAILED)[:300]
        await run_in_threadpool(db.commit)
        await run_in_threadpool(db.refresh, clone)
        return status_of(clone)

    voice_clone_id = routing.stored_id(name, voice_clone_id)
    clone.voice_clone_id = voice_clone_id
    clone.voice_clone_status = "ready"
    clone.voice_clone_error = None
    clone.voice_clone_consent_at = datetime.now(UTC)
    clone.use_cloned_voice = True
    await run_in_threadpool(db.commit)
    if previous and routing.cloned_voice_ref(previous) != voice_clone_id:
        await run_in_threadpool(delete_at_provider, previous, clone.id)
    await run_in_threadpool(db.refresh, clone)
    _log_event(clone, "created")
    return status_of(clone)


def set_use(db: Session, clone: CloneProfile, use: bool) -> VoiceCloneStatus:
    if use:
        if clone.voice_clone_status != "ready" or not clone.voice_clone_id:
            raise InvalidInputError(NOT_READY)
        if not clone.voice_consent_given:
            raise ForbiddenError(VOICE_CONSENT_REQUIRED)
    clone.use_cloned_voice = use
    db.commit()
    db.refresh(clone)
    return status_of(clone)


def delete_clone_voice(db: Session, clone: CloneProfile) -> None:
    """Delete the cloned voice at its provider (best effort) and clear it here."""
    had_voice = bool(clone.voice_clone_id) or clone.voice_clone_status != "none"
    voice_clone_id = detach(clone)
    db.commit()
    delete_at_provider(voice_clone_id, clone.id)
    if had_voice:
        _log_event(clone, "deleted")


def _log_event(clone: CloneProfile, action: str) -> None:
    """Ids and the action only (never audio)."""
    logger.info("Cloned voice %s for clone %s", action, clone.id)
