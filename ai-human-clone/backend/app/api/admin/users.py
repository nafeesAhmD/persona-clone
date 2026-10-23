import uuid
from typing import Literal

from fastapi import APIRouter, Query

from app.api.admin.common import PageLimit, PageNumber, Search
from app.api.deps import AdminUser, DbSession
from app.schemas.admin import AdminUserDetail, AdminUserRow, Page, UserStatusUpdate
from app.services import admin_service

router = APIRouter(prefix="/users")


@router.get("", response_model=Page[AdminUserRow])
def list_users(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    search: Search = None,
    status: Literal["active", "disabled", "admin"] | None = None,
    sort: Literal["created_at", "email", "username"] = "created_at",
    order: Literal["asc", "desc"] = Query(default="desc"),
) -> Page[AdminUserRow]:
    return admin_service.list_users(
        db, page=page, limit=limit, search=search, status=status, sort=sort, order=order
    )


@router.get("/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: uuid.UUID, db: DbSession) -> AdminUserDetail:
    return admin_service.user_detail(db, user_id)


@router.patch("/{user_id}/status", response_model=AdminUserDetail)
def set_status(user_id: uuid.UUID, data: UserStatusUpdate, admin: AdminUser, db: DbSession) -> AdminUserDetail:
    """Disable or reactivate an account (never deletes it). Only `is_active` can be changed."""
    return admin_service.set_user_status(db, admin, user_id, data)
