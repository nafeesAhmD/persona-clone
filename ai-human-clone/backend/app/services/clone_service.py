"""Clone CRUD and the access rules for managing and chatting with clones.

Access rules (identity always comes from the session, never from the request):
- Manage (view settings, edit, delete, knowledge): owner only. Someone else gets
  404 for a private clone (its existence isn't revealed) and 403 otherwise.
- Chat (login required): owner, or any user when the clone is public/unlisted,
  active AND public chat is on; visitors only ever get public content.
  Disabled clones can't chat at all; draft clones only with their owner.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CloneProfile, User
from app.schemas.clone import CloneCreate, CloneUpdate
from app.services import platform_service, qdrant_service
from app.services.errors import ForbiddenError, NotFoundError
from app.services.file_storage import get_file_storage
from app.services.slugs import unique_slug

logger = logging.getLogger(__name__)

NOT_FOUND = "Clone not found"
DISABLED = "This AI Clone is currently disabled."
PUBLIC_CHAT_OFF = "Public chat is turned off for this AI Clone."
ADMIN_LOCKED = "An administrator disabled this AI Clone. Contact support to restore it."
PLATFORM_CHAT_OFF = "Public chat is temporarily turned off."
# Columns that can't be set to NULL through an update.
_REQUIRED_ON_UPDATE = {"name", "skills", "response_length", "visibility", "status"}
_SLUG_ATTEMPTS = 3


def _emit(event_type: str, clone: CloneProfile, **extra) -> None:
    """Webhook event for the clone's owner (and its organization). Ids and statuses only."""
    try:
        from app.developer.webhooks import emit_for_clone

        data = {"clone_id": clone.id, "status": clone.status, "visibility": clone.visibility, **extra}
        emit_for_clone(event_type, data, owner_id=clone.owner_id, organization_id=clone.organization_id)
    except Exception as exc:  # noqa: BLE001 - webhooks must never break the request
        logger.warning("Could not emit %s: %s", event_type, type(exc).__name__)


def _slug_taken(db: Session, slug: str) -> bool:
    return db.scalar(select(CloneProfile.id).where(CloneProfile.slug == slug)) is not None


def create_clone(db: Session, data: CloneCreate, owner: User) -> CloneProfile:
    for attempt in range(_SLUG_ATTEMPTS):
        clone = CloneProfile(
            owner_id=owner.id,
            slug=unique_slug(data.name, lambda s: _slug_taken(db, s)),
            **data.model_dump(),
        )
        db.add(clone)
        try:
            db.commit()
        except IntegrityError:
            # Another request took the same slug between the check and the insert.
            db.rollback()
            if attempt == _SLUG_ATTEMPTS - 1:
                raise
            continue
        db.refresh(clone)
        logger.info("User %s created clone %s (%s)", owner.id, clone.id, clone.slug)
        _emit("clone.created", clone)
        return clone
    raise RuntimeError("unreachable")


def list_owned_clones(db: Session, owner: User) -> list[CloneProfile]:
    return list(
        db.scalars(
            select(CloneProfile)
            .where(CloneProfile.owner_id == owner.id)
            .order_by(CloneProfile.created_at.desc())
        )
    )


def list_public_clones(db: Session, limit: int | None = None) -> list[CloneProfile]:
    if not platform_service.current(db).public_clone_discovery_enabled:
        return []
    return list(
        db.scalars(
            select(CloneProfile)
            .join(User, User.id == CloneProfile.owner_id)
            .where(
                CloneProfile.visibility == "public",
                CloneProfile.status == "active",
                CloneProfile.public_chat_enabled.is_(True),
                User.is_active.is_(True),
            )
            .order_by(CloneProfile.created_at.desc())
            .limit(limit)
        )
    )


def _find(db: Session, clone_id: uuid.UUID) -> CloneProfile:
    clone = db.get(CloneProfile, clone_id)
    if clone is None:
        raise NotFoundError(NOT_FOUND)
    return clone


def get_managed_clone(db: Session, clone_id: uuid.UUID, user: User) -> CloneProfile:
    """A clone the user owns. Anyone else is refused without leaking private data."""
    clone = _find(db, clone_id)
    if clone.owner_id == user.id:
        return clone
    if clone.visibility == "private":
        raise NotFoundError(NOT_FOUND)
    raise ForbiddenError("Only the clone's owner can do this")


def get_chat_clone(db: Session, clone_id: uuid.UUID, user: User) -> CloneProfile:
    """A clone the logged-in user may chat with.

    Owner: any status except disabled. Others: only public/unlisted clones that
    are active. Visibility alone never grants access; it's checked together
    with the authenticated user here.
    """
    clone = _find(db, clone_id)
    is_owner = clone.owner_id == user.id
    if not is_owner and (clone.visibility == "private" or clone.status == "draft" or not clone.owner.is_active):
        raise NotFoundError(NOT_FOUND)  # don't reveal private or unpublished clones
    if clone.status == "disabled":
        raise ForbiddenError(DISABLED)
    if not is_owner and not clone.public_chat_enabled:
        raise ForbiddenError(PUBLIC_CHAT_OFF)
    if not is_owner and not platform_service.current(db).public_chat_enabled:
        raise ForbiddenError(PLATFORM_CHAT_OFF)
    return clone


def update_clone(db: Session, clone: CloneProfile, data: CloneUpdate) -> CloneProfile:
    changes = data.model_dump(exclude_unset=True)
    if clone.admin_disabled and changes.get("status") not in (None, "disabled"):
        raise ForbiddenError(ADMIN_LOCKED)
    for field, value in changes.items():
        if value is None and field in _REQUIRED_ON_UPDATE:
            continue  # "name": null means "leave unchanged", not "remove"
        setattr(clone, field, value)
    db.commit()  # updated_at is refreshed by the column's onupdate
    db.refresh(clone)
    _emit("clone.updated", clone, changed_fields=sorted(changes))
    return clone


def delete_clone(db: Session, clone: CloneProfile) -> None:
    """Delete a clone with its vectors, documents, stored files, conversations and
    long-term memories.

    Vectors go first: if Qdrant can't delete them, VectorStoreError (503) stops
    the whole delete so no orphaned memory is left behind.
    """
    qdrant_service.get_qdrant_service().delete_clone_chunks(clone.id)
    qdrant_service.get_memory_store().delete_clone_memories(clone.id)
    clone_id = clone.id
    voice_clone_id = clone.voice_clone_id
    db.delete(clone)
    db.commit()
    if voice_clone_id:  # the owner's cloned voice goes too (best effort, never blocks the delete)
        from app.services.voice_clone_service import delete_at_provider

        delete_at_provider(voice_clone_id, clone_id)
    # Files last: if the database delete failed, the documents still have their files.
    get_file_storage().delete_clone(clone_id)
    logger.info("Deleted clone %s", clone_id)
