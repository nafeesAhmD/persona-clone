"""Owner-only sharing controls: link name (slug), public settings, and which
documents and memories visitors may use. Everything defaults to private."""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.document import DocumentResponse
from app.schemas.memory import MemoryRead
from app.schemas.public import PublicSettingsRead, PublicSettingsUpdate, SlugUpdate, VisibilityUpdate
from app.services import clone_service, sharing_service

router = APIRouter(prefix="/clones/{clone_id}", tags=["sharing"])


@router.patch("/slug", response_model=PublicSettingsRead)
def change_slug(clone_id: uuid.UUID, data: SlugUpdate, user: CurrentUser, db: DbSession) -> PublicSettingsRead:
    """The clone's public link name: /c/{slug}. 409 if taken."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return sharing_service.settings_of(db, sharing_service.change_slug(db, clone, data.slug))


@router.get("/public-settings", response_model=PublicSettingsRead)
def get_public_settings(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> PublicSettingsRead:
    return sharing_service.settings_of(db, clone_service.get_managed_clone(db, clone_id, user))


@router.patch("/public-settings", response_model=PublicSettingsRead)
def update_public_settings(
    clone_id: uuid.UUID, data: PublicSettingsUpdate, user: CurrentUser, db: DbSession
) -> PublicSettingsRead:
    """visibility (private/unlisted/public) and public chat / voice / avatar switches.
    Turning public chat off also turns public voice and avatar off, immediately."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return sharing_service.settings_of(db, sharing_service.update_settings(db, clone, data))


@router.patch("/documents/{document_id}/visibility", response_model=DocumentResponse)
def set_document_visibility(
    clone_id: uuid.UUID, document_id: uuid.UUID, data: VisibilityUpdate, user: CurrentUser, db: DbSession
) -> DocumentResponse:
    """"public": visitors' answers may use this document. Private by default."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    document = sharing_service.set_document_visibility(db, clone, user, document_id, data.visibility)
    return DocumentResponse.model_validate(document)


@router.patch("/memories/{memory_id}/visibility", response_model=MemoryRead)
def set_memory_visibility(
    clone_id: uuid.UUID, memory_id: uuid.UUID, data: VisibilityUpdate, user: CurrentUser, db: DbSession
) -> MemoryRead:
    """"public": visitors' answers may use this memory once it is approved. Private by default."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return MemoryRead.model_validate(sharing_service.set_memory_visibility(db, clone, user, memory_id, data.visibility))
