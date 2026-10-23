import uuid
from typing import Literal

from fastapi import APIRouter

from app.api.admin.common import PageLimit, PageNumber, Search
from app.api.deps import AdminUser, DbSession
from app.schemas.admin import AdminCloneDetail, AdminCloneRow, CloneStatusUpdate, Page
from app.services import admin_service

router = APIRouter(prefix="/clones")


@router.get("", response_model=Page[AdminCloneRow])
def list_clones(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    search: Search = None,
    visibility: Literal["private", "unlisted", "public"] | None = None,
    status: Literal["draft", "active", "disabled"] | None = None,
    owner_id: uuid.UUID | None = None,
) -> Page[AdminCloneRow]:
    return admin_service.list_clones(
        db, page=page, limit=limit, search=search, visibility=visibility, status=status, owner_id=owner_id
    )


@router.get("/{clone_id}", response_model=AdminCloneDetail)
def get_clone(clone_id: uuid.UUID, db: DbSession) -> AdminCloneDetail:
    """Metadata and counts; no prompts, documents or conversations."""
    return admin_service.clone_detail(db, clone_id)


@router.patch("/{clone_id}/status", response_model=AdminCloneDetail)
def set_status(clone_id: uuid.UUID, data: CloneStatusUpdate, admin: AdminUser, db: DbSession) -> AdminCloneDetail:
    """Disable (public chat, voice and avatar stop; data kept) or re-enable a clone."""
    return admin_service.set_clone_status(db, admin, clone_id, data)
