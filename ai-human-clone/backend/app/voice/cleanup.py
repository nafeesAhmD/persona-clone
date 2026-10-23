"""Removes generated speech (VOICE_AUDIO_RETENTION_HOURS) and avatar videos (VIDEO_RETENTION_HOURS).

Runs hourly inside the API (see app/main.py lifespan), and can be run by hand:
    docker compose exec backend python -m app.voice.cleanup
"""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.voice.storage import get_voice_store

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


def cleanup_expired_audio() -> int:
    return get_voice_store().cleanup()


def cleanup_expired_videos() -> int:
    """Talking-avatar videos older than VIDEO_RETENTION_HOURS (avatars and documents stay)."""
    from app.avatar.storage import get_avatar_storage

    return get_avatar_storage().cleanup_videos()


def cleanup_expired_public_sessions() -> int:
    """Visitor sessions past PUBLIC_SESSION_TTL_HOURS, with their messages."""
    from app.db.session import SessionLocal
    from app.services.public_session_service import cleanup_expired

    with SessionLocal() as db:
        return cleanup_expired(db)


def cleanup_old_monitoring_logs() -> dict[str, int]:
    """Security, usage and error events past their *_LOG_RETENTION_DAYS (audit logs stay)."""
    from app.services.monitoring import cleanup_old_logs

    return cleanup_old_logs()


def retry_pending_voice_deletions() -> int:
    """Cloned voices a provider could not delete yet (e.g. a Colab GPU that was off)."""
    from app.services.voice_clone_service import retry_pending_deletions

    return retry_pending_deletions()


async def run_periodically(interval_seconds: float = INTERVAL_SECONDS) -> None:
    while True:
        for cleanup in (
            cleanup_expired_audio,
            cleanup_expired_videos,
            cleanup_expired_public_sessions,
            cleanup_old_monitoring_logs,
            retry_pending_voice_deletions,
        ):
            try:
                await run_in_threadpool(cleanup)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                logger.warning("Media cleanup failed: %s", exc)
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Removed {cleanup_expired_audio()} expired voice files and {cleanup_expired_videos()} expired videos")
