"""Avatar images of a clone, avatar settings and consent.

Rules:
- Callers load the clone with clone_service.get_managed_clone (owner only);
  every avatar lookup here also checks clone_id AND owner_id (IDOR-safe).
- Adding an avatar (upload or generated) needs avatar consent: permission to
  use this person's image. Turning the avatar on needs consent and a ready
  active avatar. Withdrawing consent turns the avatar off.
- One avatar per clone is active; deleting it activates the newest other one.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.avatar import factory
from app.avatar.base import AvatarImage, AvatarStyle
from app.avatar.image_processor import process_upload
from app.avatar.providers.illustrated import PRESETS
from app.avatar.storage import get_avatar_storage
from app.core.config import get_settings
from app.models import CloneAvatar, CloneProfile, User
from app.schemas.avatar import (
    AvatarGenerateRequest,
    AvatarPreset,
    AvatarRead,
    AvatarSettingsRead,
    AvatarUpdate,
)
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)

NOT_FOUND = "Avatar not found"
CONSENT_REQUIRED = "Avatar consent is required first: confirm you have permission to use this image."
NO_AVATAR = "Add an avatar image first."


def image_url(avatar: CloneAvatar) -> str:
    return f"/api/clones/{avatar.clone_id}/avatar/{avatar.id}/image"


def to_read(avatar: CloneAvatar) -> AvatarRead:
    return AvatarRead.model_validate({**avatar.__dict__, "image_url": image_url(avatar)})


def list_avatars(db: Session, clone: CloneProfile) -> list[CloneAvatar]:
    return list(
        db.scalars(
            select(CloneAvatar)
            .where(CloneAvatar.clone_id == clone.id, CloneAvatar.owner_id == clone.owner_id)
            .order_by(CloneAvatar.created_at.desc())
        )
    )


def active_avatar(db: Session, clone: CloneProfile) -> CloneAvatar | None:
    return db.scalar(
        select(CloneAvatar).where(
            CloneAvatar.clone_id == clone.id, CloneAvatar.owner_id == clone.owner_id, CloneAvatar.is_active.is_(True)
        )
    )


def get_avatar(db: Session, clone: CloneProfile, user: User, avatar_id: uuid.UUID) -> CloneAvatar:
    avatar = db.get(CloneAvatar, avatar_id)
    if avatar is None or avatar.clone_id != clone.id or avatar.owner_id != user.id:
        raise NotFoundError(NOT_FOUND)
    return avatar


def settings_of(db: Session, clone: CloneProfile) -> AvatarSettingsRead:
    avatars = list_avatars(db, clone)
    active = next((a for a in avatars if a.is_active), None)
    return AvatarSettingsRead(
        avatar_enabled=clone.avatar_enabled,
        avatar_consent_given=clone.avatar_consent_given,
        avatar_consent_at=clone.avatar_consent_at,
        active_avatar=to_read(active) if active else None,
        avatars=[to_read(a) for a in avatars],
        presets=[AvatarPreset(id=key, name=key.title()) for key in PRESETS],
        lipsync_provider=factory.lipsync_provider_name(),
        voice_enabled=clone.voice_enabled,
        max_video_seconds=get_settings().max_video_duration_seconds,
    )


def _reset_live_face(clone: CloneProfile) -> None:
    """The live (video call) face was made from the previous photo: start over."""
    clone.live_face_id = None
    clone.live_face_status = "none"
    clone.live_face_error = None


def _require_consent(clone: CloneProfile) -> None:
    if not clone.avatar_consent_given:
        raise ForbiddenError(CONSENT_REQUIRED)


def _add(db: Session, clone: CloneProfile, user: User, image: AvatarImage, avatar_type: str) -> CloneAvatar:
    storage = get_avatar_storage()
    name = storage.save_image(clone.id, image.png)
    db.execute(update(CloneAvatar).where(CloneAvatar.clone_id == clone.id).values(is_active=False))
    _reset_live_face(clone)
    avatar = CloneAvatar(
        clone_id=clone.id,
        owner_id=user.id,
        image_path=name,
        avatar_type=avatar_type,
        status="ready",
        is_active=True,
        width=image.width,
        height=image.height,
        mouth_x=image.mouth.x,
        mouth_y=image.mouth.y,
        mouth_width=image.mouth.width,
        face_detected=image.face_detected,
        error_message=None if image.face_detected else "No face was found. Set the mouth position by hand.",
    )
    db.add(avatar)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(clone.id, "avatar", name)
        raise
    db.refresh(avatar)
    logger.info("Clone %s got a new %s avatar %s", clone.id, avatar_type, avatar.id)
    return avatar


def upload(
    db: Session, clone: CloneProfile, user: User, data: bytes, filename: str | None, content_type: str | None
) -> CloneAvatar:
    _require_consent(clone)
    return _add(db, clone, user, process_upload(data, filename, content_type), "uploaded")


def generate(db: Session, clone: CloneProfile, user: User, request: AvatarGenerateRequest) -> CloneAvatar:
    _require_consent(clone)
    provider = factory.get_avatar_provider()
    if request.preset is not None:
        style = provider.presets().get(request.preset)
        if style is None:
            raise InvalidInputError("Unknown avatar preset")
        return _add(db, clone, user, provider.generate(style), "preset")
    assert request.style is not None
    return _add(db, clone, user, provider.generate(AvatarStyle(**request.style.model_dump())), "generated")


def update_settings(db: Session, clone: CloneProfile, user: User, data: AvatarUpdate) -> CloneProfile:
    changes = data.model_dump(exclude_unset=True)

    if changes.get("avatar_consent_given") is True and not clone.avatar_consent_given:
        clone.avatar_consent_given = True
        clone.avatar_consent_at = datetime.now(UTC)
    elif changes.get("avatar_consent_given") is False:
        clone.avatar_consent_given = False
        clone.avatar_consent_at = None
        clone.avatar_enabled = False  # no avatar without consent
        _reset_live_face(clone)

    if changes.get("active_avatar_id"):
        chosen = get_avatar(db, clone, user, changes["active_avatar_id"])
        if not chosen.is_active:
            _reset_live_face(clone)
        db.execute(update(CloneAvatar).where(CloneAvatar.clone_id == clone.id).values(is_active=False))
        chosen.is_active = True

    mouth = {key: changes[key] for key in ("mouth_x", "mouth_y", "mouth_width") if changes.get(key) is not None}
    if mouth:
        db.flush()
        current = active_avatar(db, clone)
        if current is None:
            raise InvalidInputError(NO_AVATAR)
        for key, value in mouth.items():
            setattr(current, key, round(value, 4))

    if changes.get("avatar_enabled") is True:
        _require_consent(clone)
        db.flush()
        current = active_avatar(db, clone)
        if current is None or current.status != "ready":
            raise InvalidInputError(NO_AVATAR)
        clone.avatar_enabled = True
    elif changes.get("avatar_enabled") is False:
        clone.avatar_enabled = False

    db.commit()
    db.refresh(clone)
    return clone


def delete(db: Session, clone: CloneProfile, avatar: CloneAvatar) -> None:
    was_active = avatar.is_active
    name = avatar.image_path
    db.delete(avatar)
    db.flush()
    if was_active:
        _reset_live_face(clone)
        replacement = db.scalar(
            select(CloneAvatar).where(CloneAvatar.clone_id == clone.id).order_by(CloneAvatar.created_at.desc())
        )
        if replacement is not None:
            replacement.is_active = True
        else:
            clone.avatar_enabled = False
    db.commit()
    get_avatar_storage().delete(clone.id, "avatar", name)  # after the row is gone


def image_path(avatar: CloneAvatar):
    path = get_avatar_storage().path(avatar.clone_id, "avatar", avatar.image_path)
    if not path.is_file():
        raise NotFoundError("The avatar image is missing")
    return path
