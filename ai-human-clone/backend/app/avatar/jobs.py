"""Background rendering of talking-avatar videos.

A small in-process worker pool (AVATAR_VIDEO_WORKERS threads, default 1),
because rendering is CPU-bound and short. No extra services: jobs live in
the avatar_video_jobs table, so a real queue (RQ/Celery) can replace submit()
later without changing the API. Jobs still running when the server stops are
marked failed on the next start, so clients never poll forever.

Per job: speech (Phase 7 TTS, reused if that answer was already spoken) ->
lip-sync provider -> MP4 in storage/clones/{clone_id}/videos.
"""

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.avatar import factory
from app.avatar.base import AvatarError, LipSyncRequest, MouthPosition
from app.avatar.storage import get_avatar_storage
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AvatarVideoJob, CloneAvatar, CloneProfile, Message, PublicChatMessage
from app.services import monitoring
from app.voice.base import VoiceError
from app.voice.routing import effective_voice
from app.voice.storage import get_voice_store
from app.voice.text_to_speech import generate_speech

logger = logging.getLogger(__name__)

INTERRUPTED = "Video generation was interrupted. Please try again."
FAILED = "The avatar video couldn't be generated. The text and voice answer are still available."


class JobCancelled(Exception):
    pass


# The API's event loop. Async provider clients (e.g. the TTS client) are shared and
# bound to the loop they first ran on, so worker threads must run coroutines there,
# never in a throwaway asyncio.run() loop ("Event loop is closed" afterwards).
_app_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _app_loop
    _app_loop = loop


def _run_async(coroutine):
    loop = _app_loop
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()
    return asyncio.run(coroutine)  # no app loop (e.g. a script): a private loop is fine


@lru_cache
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=max(1, get_settings().avatar_video_workers), thread_name_prefix="avatar-video")


def submit(job_id: uuid.UUID) -> None:
    _executor().submit(run_job, job_id)


def shutdown() -> None:
    """At app shutdown: drop queued jobs (recover_interrupted fails them on the next
    start, so clients stop waiting) and don't block on running ones."""
    if _executor.cache_info().currsize:
        _executor().shutdown(wait=False, cancel_futures=True)
        _executor.cache_clear()


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(db: Session, job: AvatarVideoJob, message: str) -> None:
    db.rollback()
    db.refresh(job)
    if job.status == "cancelled":
        return
    job.status = "failed"
    job.error_message = message[:300]
    job.completed_at = _now()
    db.commit()
    _record(job, "failed")


def _record(job: AvatarVideoJob, status: str) -> None:
    """Usage only: seconds of video and render time; visitors' jobs carry no account."""
    started = job.started_at or job.created_at
    elapsed = (_now() - _aware(started)).total_seconds() if started else None
    monitoring.usage(
        "AVATAR_JOB",
        provider=job.provider,
        status=status,
        user_id=None if job.public_session_id else job.owner_id,
        clone_id=job.clone_id,
        output_units=job.duration_seconds,
        duration_ms=int(elapsed * 1000) if elapsed is not None else None,
    )


def _emit_completed(job: AvatarVideoJob, clone: CloneProfile) -> None:
    """Webhook event for the clone's owner (and organization): ids and numbers, no paths."""
    try:
        from app.developer.webhooks import emit_for_clone

        emit_for_clone(
            "avatar.completed",
            {
                "job_id": job.id,
                "clone_id": clone.id,
                "message_id": job.message_id,
                "status": job.status,
                "duration_seconds": job.duration_seconds,
                "provider": job.provider,
                "requested_by": "visitor" if job.public_session_id else "owner",
            },
            owner_id=clone.owner_id,
            organization_id=clone.organization_id,
        )
    except Exception as exc:  # noqa: BLE001 - the job is done either way
        logger.warning("Could not emit avatar.completed: %s", type(exc).__name__)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _progress_writer(db: Session, job_id: uuid.UUID):
    last = -1

    def write(value: int) -> None:
        nonlocal last
        value = max(0, min(99, int(value)))
        if value == last:
            return
        last = value
        result = db.execute(
            update(AvatarVideoJob)
            .where(AvatarVideoJob.id == job_id, AvatarVideoJob.status == "processing")
            .values(progress=value)
        )
        db.commit()
        if result.rowcount == 0:  # cancelled (or removed) meanwhile
            raise JobCancelled

    return write


def run_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(AvatarVideoJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status, job.started_at, job.progress = "processing", _now(), 5
        db.commit()
        storage = get_avatar_storage()
        partial = None
        try:
            clone = db.get(CloneProfile, job.clone_id)
            avatar = db.get(CloneAvatar, job.avatar_id) if job.avatar_id else None
            if clone is None or avatar is None or avatar.status != "ready":
                raise AvatarError("The avatar is no longer available")
            message = db.get(Message, job.message_id) if job.message_id else None
            public_message = db.get(PublicChatMessage, job.public_message_id) if job.public_message_id else None
            text = (message or public_message).content if (message or public_message) else job.text
            if not text:
                raise AvatarError("There is nothing to say")
            # Reuse the answer's voice reply if it was already spoken (same key as voice replies);
            # a visitor's audio is stored under their session, the owner's under the owner.
            if message:
                cache_key = str(message.id)
            elif public_message:
                cache_key = f"public:{public_message.id}"
            else:
                cache_key = None
            audio_owner = job.public_session_id or job.owner_id

            from app.services.voice_service import speech_language  # avoid an import cycle

            speech = _run_async(
                generate_speech(
                    text, effective_voice(clone), speech_language(clone, text), user_id=audio_owner,
                    cache_key=cache_key,
                    account_id=None if job.public_session_id else job.owner_id,
                    clone_id=clone.id,
                )
            )
            audio = get_voice_store().find(audio_owner, speech.audio_id)
            if audio is None:
                raise AvatarError("The speech audio is missing")
            job.input_audio_path = speech.audio_id
            job.progress = 12
            db.commit()

            provider = factory.get_lipsync_provider()
            name, final = storage.new_path(clone.id, "videos")
            partial = final.with_name(final.stem + ".part")
            settings = get_settings()
            duration = provider.render(
                LipSyncRequest(
                    image_path=storage.path(clone.id, "avatar", avatar.image_path),
                    audio_path=audio,
                    output_path=partial,
                    mouth=MouthPosition(avatar.mouth_x, avatar.mouth_y, avatar.mouth_width),
                    face_detected=avatar.face_detected,
                    max_seconds=settings.max_video_duration_seconds,
                    fps=settings.avatar_video_fps,
                ),
                _progress_writer(db, job.id),
            )
            partial.replace(final)
            partial = None
            db.refresh(job)
            if job.status == "cancelled":
                storage.delete(clone.id, "videos", name)
                return
            job.output_video_path, job.duration_seconds = name, duration
            job.status, job.progress, job.completed_at = "completed", 100, _now()
            db.commit()
            _record(job, "success")
            logger.info("Avatar video job %s completed (%.1fs, %s)", job.id, duration, job.provider)
            _emit_completed(job, clone)
        except JobCancelled:
            logger.info("Avatar video job %s was cancelled", job_id)
        except VoiceError as exc:
            logger.warning("Avatar video job %s: speech failed (%s): %s", job_id, type(exc).__name__, exc)
            _fail(db, job, f"{exc.user_message} The text answer is still available.")
        except AvatarError as exc:
            logger.warning("Avatar video job %s failed (%s): %s", job_id, type(exc).__name__, exc)
            _fail(db, job, FAILED if type(exc) is AvatarError else exc.user_message)
        except Exception:  # noqa: BLE001 - the job must always end
            logger.exception("Avatar video job %s crashed", job_id)
            _fail(db, job, FAILED)
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)


def recover_interrupted() -> int:
    """Mark jobs left queued/processing by a previous run as failed."""
    try:
        with SessionLocal() as db:
            result = db.execute(
                update(AvatarVideoJob)
                .where(AvatarVideoJob.status.in_(("queued", "processing")))
                .values(status="failed", error_message=INTERRUPTED, completed_at=_now())
            )
            db.commit()
            if result.rowcount:
                logger.info("Marked %d interrupted avatar video jobs as failed", result.rowcount)
            return result.rowcount
    except Exception as exc:  # noqa: BLE001 - startup must not fail on this
        logger.warning("Could not recover avatar video jobs: %s", exc)
        return 0
