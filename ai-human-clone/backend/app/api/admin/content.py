"""Moderation of what visitors can see. Actions hide content; they never delete it."""

import uuid

from fastapi import APIRouter, status

from app.api.admin.common import PageLimit, PageNumber, Search
from app.api.deps import AdminUser, DbSession
from app.schemas.admin import (
    AdminCloneDetail,
    CloneStatusUpdate,
    ModerationAction,
    Page,
    PublicCloneItem,
    PublicDocumentItem,
    PublicMemoryItem,
)
from app.services import admin_service

router = APIRouter(prefix="/content")


@router.get("/public-clones", response_model=Page[PublicCloneItem])
def public_clones(db: DbSession, page: PageNumber = 1, limit: PageLimit = 20, search: Search = None):
    return admin_service.public_clones(db, page=page, limit=limit, search=search)


@router.get("/public-documents", response_model=Page[PublicDocumentItem])
def public_documents(db: DbSession, page: PageNumber = 1, limit: PageLimit = 20):
    """Titles and sizes only; document text isn't returned."""
    return admin_service.public_documents(db, page=page, limit=limit)


@router.get("/public-memories", response_model=Page[PublicMemoryItem])
def public_memories(db: DbSession, page: PageNumber = 1, limit: PageLimit = 20):
    return admin_service.public_memories(db, page=page, limit=limit)


@router.post("/clones/{clone_id}/make-private", status_code=status.HTTP_204_NO_CONTENT)
def make_clone_private(clone_id: uuid.UUID, data: ModerationAction, admin: AdminUser, db: DbSession) -> None:
    admin_service.make_clone_private(db, admin, clone_id, data.reason)


@router.post("/clones/{clone_id}/disable", response_model=AdminCloneDetail)
def disable_clone(clone_id: uuid.UUID, data: ModerationAction, admin: AdminUser, db: DbSession):
    return admin_service.set_clone_status(
        db, admin, clone_id, CloneStatusUpdate(status="disabled", reason=data.reason), action_prefix="PUBLIC_CLONE"
    )


@router.post("/documents/{document_id}/make-private", status_code=status.HTTP_204_NO_CONTENT)
def make_document_private(document_id: uuid.UUID, data: ModerationAction, admin: AdminUser, db: DbSession) -> None:
    admin_service.make_document_private(db, admin, document_id, data.reason)


@router.post("/memories/{memory_id}/make-private", status_code=status.HTTP_204_NO_CONTENT)
def make_memory_private(memory_id: uuid.UUID, data: ModerationAction, admin: AdminUser, db: DbSession) -> None:
    admin_service.make_memory_private(db, admin, memory_id, data.reason)
