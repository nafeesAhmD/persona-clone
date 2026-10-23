"""Talking-avatar videos through the API (scope avatar:generate).

- POST /clones/{id}/avatar/video: {"text"} for a short test video, or
  {"conversation_id", "message_id"} for a video of one of the clone's answers.
- GET /clones/{id}/avatar/jobs/{job_id}: job status (poll until completed).
- GET /clones/{id}/avatar/jobs/{job_id}/video: the MP4 once completed.

Jobs run as the clone owner through lip_sync_service, which enforces avatar consent,
avatar and voice turned on, a ready avatar and the per-user video rate limit; this
module adds the plan's monthly avatar_requests. Answer videos need a conversation this
key can access (access.get_conversation). Video URLs point to this API, never to
internal routes or file paths.
"""

import uuid

from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.avatar import lip_sync_service
from app.developer import access, feature_limits
from app.developer.auth import Scoped
from app.developer.errors import ApiError
from app.models import AvatarVideoJob
from app.schemas.api_v1 import ApiAvatarJob, ApiAvatarVideoRequest

router = APIRouter(tags=["Avatar"])


def _job_read(job: AvatarVideoJob) -> ApiAvatarJob:
    internal = lip_sync_service.to_read(job)
    return ApiAvatarJob(
        job_id=internal.job_id,
        status=internal.status,
        progress=internal.progress,
        video_url=f"/api/v1/clones/{job.clone_id}/avatar/jobs/{job.id}/video" if internal.video_url else None,
        expired=internal.expired,
        error_message=internal.error_message,
        duration_seconds=internal.duration_seconds,
        conversation_id=internal.conversation_id,
        message_id=internal.message_id,
        created_at=internal.created_at,
        completed_at=internal.completed_at,
    )


@router.post(
    "/clones/{clone_id}/avatar/video",
    response_model=ApiAvatarJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a talking-avatar video",
)
def create_video(
    clone_id: uuid.UUID,
    data: ApiAvatarVideoRequest,
    request: Request,
    principal: Scoped("avatar:generate"),
    db: DbSession,
) -> ApiAvatarJob:
    """Start a video job: `text` (a test video, ≤ 500 characters) or `conversation_id` +
    `message_id` (an answer of the clone). Poll the job for the result. Scope: `avatar:generate`.
    The owner must have given avatar consent and turned the avatar and voice on."""
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    if data.conversation_id is not None:
        _, conversation_clone = access.get_conversation(db, principal, data.conversation_id)
        if conversation_clone.id != clone.id:
            raise ApiError(404, "resource_not_found", "Conversation not found.")
    feature_limits.check(db, principal, owner.id, "avatar_requests")
    if data.text:
        job = lip_sync_service.create_test_video(db, clone, owner, data.text)
    else:
        job = lip_sync_service.create_answer_video(db, clone, owner, data.conversation_id, data.message_id)
    db.refresh(job)
    feature_limits.record("API_AVATAR", principal, request, clone)
    return _job_read(job)


@router.get("/clones/{clone_id}/avatar/jobs/{job_id}", response_model=ApiAvatarJob, summary="Get a video job")
def get_job(
    clone_id: uuid.UUID, job_id: uuid.UUID, request: Request, principal: Scoped("avatar:generate"), db: DbSession
) -> ApiAvatarJob:
    """A video job's status and, once completed, its `video_url`. Scope: `avatar:generate`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    return _job_read(lip_sync_service.get_job(db, clone, access.acting_user(db, clone), job_id))


@router.get(
    "/clones/{clone_id}/avatar/jobs/{job_id}/video",
    response_class=FileResponse,
    summary="Download a video",
    responses={200: {"content": {"video/mp4": {}}, "description": "The MP4 video."}},
)
def get_video(
    clone_id: uuid.UUID, job_id: uuid.UUID, request: Request, principal: Scoped("avatar:generate"), db: DbSession
):
    """The completed video (MP4) until it expires. Scope: `avatar:generate`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    job = lip_sync_service.get_job(db, clone, access.acting_user(db, clone), job_id)
    return FileResponse(lip_sync_service.video_file(job), media_type="video/mp4", headers={"Cache-Control": "no-store"})
