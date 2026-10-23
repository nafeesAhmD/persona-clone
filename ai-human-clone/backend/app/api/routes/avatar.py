"""Avatar images, avatar settings and talking-avatar video jobs. Owner only.

Every route loads the clone with get_managed_clone (404 for someone else's
private clone, 403 otherwise); avatars and jobs are then looked up within that
clone and owner. Files are served only through these routes.
"""

import uuid

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.avatar import avatar_service, lip_sync_service
from app.avatar.base import InvalidImageError
from app.avatar.image_processor import max_avatar_bytes, too_large_message
from app.schemas.avatar import (
    AvatarGenerateRequest,
    AvatarJobCreated,
    AvatarJobRead,
    AvatarRead,
    AvatarSettingsRead,
    AvatarTestRequest,
    AvatarUpdate,
    AvatarVideoRequest,
)
from app.services import clone_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/clones/{clone_id}/avatar", tags=["avatar"])
# Never cached by the browser: on a shared computer the next user must not get them.
_PRIVATE = {"Cache-Control": "no-store", "Vary": "Cookie"}


@router.get("", response_model=AvatarSettingsRead)
def get_avatar_settings(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AvatarSettingsRead:
    return avatar_service.settings_of(db, clone_service.get_managed_clone(db, clone_id, user))


@router.post("", response_model=AvatarRead, status_code=status.HTTP_201_CREATED)
def upload_avatar(clone_id: uuid.UUID, user: CurrentUser, db: DbSession, image: UploadFile = File(...)) -> AvatarRead:
    """Upload a JPG, PNG or WebP portrait (needs avatar consent). It becomes the active avatar."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    data = image.file.read(max_avatar_bytes() + 1)
    if len(data) > max_avatar_bytes():
        raise InvalidImageError(too_large_message(), 413)
    return avatar_service.to_read(avatar_service.upload(db, clone, user, data, image.filename, image.content_type))


@router.patch("", response_model=AvatarSettingsRead)
def update_avatar_settings(clone_id: uuid.UUID, data: AvatarUpdate, user: CurrentUser, db: DbSession) -> AvatarSettingsRead:
    """Consent, avatar on/off, which avatar is active, and the mouth position."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return avatar_service.settings_of(db, avatar_service.update_settings(db, clone, user, data))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_active_avatar(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    avatar = avatar_service.active_avatar(db, clone)
    if avatar is None:
        raise NotFoundError(avatar_service.NOT_FOUND)
    avatar_service.delete(db, clone, avatar)


@router.post("/generate", response_model=AvatarRead, status_code=status.HTTP_201_CREATED)
def generate_avatar(
    clone_id: uuid.UUID, data: AvatarGenerateRequest, user: CurrentUser, db: DbSession
) -> AvatarRead:
    """A built-in illustrated avatar: a preset, or your own colours and hair style."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return avatar_service.to_read(avatar_service.generate(db, clone, user, data))


# --- Video jobs ---------------------------------------------------------------------


@router.post("/video", response_model=AvatarJobCreated, status_code=status.HTTP_202_ACCEPTED)
def create_answer_video(clone_id: uuid.UUID, data: AvatarVideoRequest, user: CurrentUser, db: DbSession) -> AvatarJobCreated:
    """Start a talking-avatar video of one of the clone's answers. Poll the job for the result."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    job = lip_sync_service.create_answer_video(db, clone, user, data.conversation_id, data.message_id)
    return AvatarJobCreated(job_id=job.id, status=job.status)  # type: ignore[arg-type]


@router.post("/test", response_model=AvatarJobCreated, status_code=status.HTTP_202_ACCEPTED)
def create_test_video(clone_id: uuid.UUID, data: AvatarTestRequest, user: CurrentUser, db: DbSession) -> AvatarJobCreated:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    job = lip_sync_service.create_test_video(db, clone, user, data.text)
    return AvatarJobCreated(job_id=job.id, status=job.status)  # type: ignore[arg-type]


@router.get("/jobs/{job_id}", response_model=AvatarJobRead)
def get_job(clone_id: uuid.UUID, job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AvatarJobRead:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return lip_sync_service.to_read(lip_sync_service.get_job(db, clone, user, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=AvatarJobRead)
def cancel_job(clone_id: uuid.UUID, job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AvatarJobRead:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    job = lip_sync_service.get_job(db, clone, user, job_id)
    return lip_sync_service.to_read(lip_sync_service.cancel(db, job))


@router.get("/jobs/{job_id}/video", response_class=FileResponse)
def get_video(clone_id: uuid.UUID, job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FileResponse:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    path = lip_sync_service.video_file(lip_sync_service.get_job(db, clone, user, job_id))
    return FileResponse(path, media_type="video/mp4", headers=_PRIVATE)


# --- One avatar ---------------------------------------------------------------------


@router.get("/{avatar_id}/image", response_class=FileResponse)
def get_avatar_image(clone_id: uuid.UUID, avatar_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FileResponse:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    avatar = avatar_service.get_avatar(db, clone, user, avatar_id)
    return FileResponse(avatar_service.image_path(avatar), media_type="image/png", headers=_PRIVATE)


@router.delete("/{avatar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(clone_id: uuid.UUID, avatar_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    avatar_service.delete(db, clone, avatar_service.get_avatar(db, clone, user, avatar_id))
