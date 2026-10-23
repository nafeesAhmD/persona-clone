from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.admin import PlatformStatus
from app.services import admin_service

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/status", response_model=PlatformStatus)
def status(db: DbSession) -> PlatformStatus:
    """Public switches for the frontend (maintenance banner, registration, discovery)."""
    return admin_service.platform_status(db)
