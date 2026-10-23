"""Owner-side public settings: slug, visibility, public switches, public content.

Callers load the clone with clone_service.get_managed_clone (owner only), and
documents/memories are looked up within that clone and owner.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CloneMemory, CloneProfile, Document, User
from app.schemas.public import PublicSettingsRead, PublicSettingsUpdate
from app.core.config import get_settings
from app.services import memory_service
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.public_service import avatar_available

logger = logging.getLogger(__name__)

SLUG_TAKEN = "This link name is already taken. Try another one."
VOICE_FIRST = "Set up voice for this clone first (Voice settings), then allow it for visitors."
AVATAR_FIRST = "Set up and turn on the avatar first (Avatar settings), then allow it for visitors."
CHAT_FIRST = "Turn on public chat first."


def share_path(clone: CloneProfile) -> str:
    return f"/c/{clone.slug}"


def share_url(clone: CloneProfile) -> str:
    settings = get_settings()
    base = (settings.public_site_url or settings.frontend_url).rstrip("/")
    return f"{base}{share_path(clone)}"


def settings_of(db: Session, clone: CloneProfile) -> PublicSettingsRead:
    public_documents = db.scalar(
        select(func.count()).where(Document.clone_id == clone.id, Document.visibility == "public")
    )
    public_memories = db.scalar(
        select(func.count()).where(
            CloneMemory.clone_id == clone.id, CloneMemory.visibility == "public", CloneMemory.status == "approved"
        )
    )
    return PublicSettingsRead(
        slug=clone.slug,
        visibility=clone.visibility,  # type: ignore[arg-type]
        public_chat_enabled=clone.public_chat_enabled,
        public_voice_enabled=clone.public_voice_enabled,
        public_avatar_enabled=clone.public_avatar_enabled,
        voice_available=clone.voice_enabled and clone.voice_consent_given,
        avatar_available=clone.avatar_enabled and clone.avatar_consent_given,
        public_document_count=public_documents or 0,
        public_memory_count=public_memories or 0,
        share_path=share_path(clone),
        share_url=share_url(clone),
    )


def update_settings(db: Session, clone: CloneProfile, data: PublicSettingsUpdate) -> CloneProfile:
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "visibility" in changes:
        clone.visibility = changes["visibility"]
    if "public_chat_enabled" in changes:
        clone.public_chat_enabled = changes["public_chat_enabled"]
        if not clone.public_chat_enabled:  # voice and avatar are part of public chat
            clone.public_voice_enabled = False
            clone.public_avatar_enabled = False
    if changes.get("public_voice_enabled") is True:
        if not clone.public_chat_enabled:
            raise InvalidInputError(CHAT_FIRST)
        if not (clone.voice_enabled and clone.voice_consent_given):
            raise InvalidInputError(VOICE_FIRST)
        clone.public_voice_enabled = True
    elif changes.get("public_voice_enabled") is False:
        clone.public_voice_enabled = False
    if changes.get("public_avatar_enabled") is True:
        if not clone.public_chat_enabled:
            raise InvalidInputError(CHAT_FIRST)
        clone.public_avatar_enabled = True
        if not avatar_available(db, clone):
            db.rollback()
            raise InvalidInputError(AVATAR_FIRST)
    elif changes.get("public_avatar_enabled") is False:
        clone.public_avatar_enabled = False
    db.commit()
    db.refresh(clone)
    if changes:
        from app.services.clone_service import _emit

        _emit("clone.updated", clone, changed_fields=sorted(changes))
    logger.info(
        "Clone %s public settings: visibility=%s chat=%s voice=%s avatar=%s",
        clone.id,
        clone.visibility,
        clone.public_chat_enabled,
        clone.public_voice_enabled,
        clone.public_avatar_enabled,
    )
    return clone


def change_slug(db: Session, clone: CloneProfile, slug: str) -> CloneProfile:
    if slug == clone.slug:
        return clone
    if db.scalar(select(CloneProfile.id).where(CloneProfile.slug == slug)) is not None:
        raise ConflictError(SLUG_TAKEN)
    clone.slug = slug
    try:
        db.commit()
    except IntegrityError as exc:  # taken between the check and the update
        db.rollback()
        raise ConflictError(SLUG_TAKEN) from exc
    from app.services.clone_service import _emit

    _emit("clone.updated", clone, changed_fields=["slug"])
    db.refresh(clone)
    return clone


def set_document_visibility(
    db: Session, clone: CloneProfile, user: User, document_id: uuid.UUID, visibility: str
) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.clone_id != clone.id or document.owner_id != user.id:
        raise NotFoundError("Document not found")
    document.visibility = visibility
    db.commit()
    db.refresh(document)
    return document


def set_memory_visibility(
    db: Session, clone: CloneProfile, user: User, memory_id: uuid.UUID, visibility: str
) -> CloneMemory:
    memory = memory_service.get_memory(db, clone, user, memory_id)
    memory.visibility = visibility
    db.commit()
    db.refresh(memory)
    return memory
