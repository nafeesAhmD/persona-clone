from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.schemas.admin import PlatformSettingsRead, PlatformSettingsUpdate
from app.services import admin_service

router = APIRouter(prefix="/settings")


@router.get("", response_model=PlatformSettingsRead)
def get_settings(db: DbSession) -> PlatformSettingsRead:
    """Platform switches and rate-limit overrides. Secrets are never stored or shown here."""
    return admin_service.get_platform_settings(db)


@router.patch("", response_model=PlatformSettingsRead)
def update_settings(data: PlatformSettingsUpdate, admin: AdminUser, db: DbSession) -> PlatformSettingsRead:
    return admin_service.update_platform_settings(db, admin, data)
