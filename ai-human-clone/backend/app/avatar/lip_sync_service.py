"""Talking-avatar video jobs: create, check, cancel, serve.

Videos are an extra layer after the normal answer: the chat (RAG, memory,
LLM) and the voice (Phase 7 TTS) are reused as they are. A video is made only
when asked for (avatar response mode or a test), never for every message.

Owner only (callers use get_managed_clone), and every job lookup checks
clone_id AND owner_id. Answer videos must be for an assistant message in the
owner's own conversation with this clone; no file paths or audio URLs are
accepted from the client.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.avatar import avatar_service, factory, jobs
from app.avatar.storage import get_avatar_storage
from app.core.config import get_settings
from app.models import AvatarVideoJob, CloneProfile, Message, User
from app.schemas.avatar import AvatarJobRead
from app.services import conversation_service
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError
from app.services.rate_limit import check_avatar_video_rate

logger = logging.getLogger(__name__)

JOB_NOT_FOUND = "Video job not found"
AVATAR_OFF = "The avatar is turned off for this AI Clone."
VOICE_NEEDED = "Turn on voice first: the avatar speaks with the clone's voice."


def video_url(job: AvatarVideoJob) -> str:
    return f"/api/clones/{job.clone_id}/avatar/jobs/{job.id}/video"


def to_read(job: AvatarVideoJob) -> AvatarJobRead:
    fresh = job.status == "completed" and get_avatar_storage().video_if_fresh(job.clone_id, job.output_video_path)
    return AvatarJobRead(
        job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        video_url=video_url(job) if fresh else None,
        expired=job.status == "completed" and not fresh,
        error_message=job.error_message,
        duration_seconds=job.duration_seconds,
        conversation_id=job.conversation_id,
        message_id=job.message_id,
        provider=job.provider,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _require_ready(db: Session, clone: CloneProfile):
    if not get_settings().avatar_feature_enabled:
        raise ForbiddenError("Avatar videos are turned off on this server.")
    if not (clone.avatar_enabled and clone.avatar_consent_given):
        raise ForbiddenError(AVATAR_OFF)
    if not (clone.voice_enabled and clone.voice_consent_given):
        raise ForbiddenError(VOICE_NEEDED)
    avatar = avatar_service.active_avatar(db, clone)
    if avatar is None or avatar.status != "ready":
        raise InvalidInputError(avatar_service.NO_AVATAR)
    return avatar


def _create(db: Session, clone: CloneProfile, user: User, **fields) -> AvatarVideoJob:
    avatar = _require_ready(db, clone)
    provider = factory.get_lipsync_provider()  # 503 if videos are off
    check_avatar_video_rate(user.id)
    job = AvatarVideoJob(
        clone_id=clone.id,
        owner_id=user.id,
        avatar_id=avatar.id,
        provider=provider.name,
        status="queued",
        progress=0,
        **fields,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    jobs.submit(job.id)
    return job


def create_answer_video(
    db: Session, clone: CloneProfile, user: User, conversation_id: uuid.UUID, message_id: uuid.UUID
) -> AvatarVideoJob:
    conversation = conversation_service.get_owned(db, conversation_id, user)
    if conversation.clone_id != clone.id:
        raise NotFoundError("Conversation not found")
    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id or message.role != "assistant":
        raise NotFoundError("Message not found")
    return _create(db, clone, user, conversation_id=conversation.id, message_id=message.id)


def create_test_video(db: Session, clone: CloneProfile, user: User, text: str) -> AvatarVideoJob:
    return _create(db, clone, user, text=text)


def get_job(db: Session, clone: CloneProfile, user: User, job_id: uuid.UUID) -> AvatarVideoJob:
    job = db.get(AvatarVideoJob, job_id)
    # Visitors' videos (public_session_id) belong to their sessions, not to the owner.
    if job is None or job.clone_id != clone.id or job.owner_id != user.id or job.public_session_id is not None:
        raise NotFoundError(JOB_NOT_FOUND)
    return job


def cancel(db: Session, job: AvatarVideoJob) -> AvatarVideoJob:
    if job.status in ("queued", "processing"):
        job.status = "cancelled"
        db.commit()
        db.refresh(job)
    return job


def video_file(job: AvatarVideoJob):
    path = get_avatar_storage().video_if_fresh(job.clone_id, job.output_video_path) if job.status == "completed" else None
    if path is None:
        raise NotFoundError("The video isn't ready or has expired")
    return path


def latest_jobs_for(db: Session, user: User, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, AvatarVideoJob]:
    """The newest video job per message (for showing videos again after a reload)."""
    if not message_ids:
        return {}
    rows = db.scalars(
        select(AvatarVideoJob)
        .where(AvatarVideoJob.message_id.in_(message_ids), AvatarVideoJob.owner_id == user.id)
        .order_by(AvatarVideoJob.created_at)
    )
    return {job.message_id: job for job in rows if job.message_id}

