from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.admin import DashboardStats
from app.services import admin_service

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: DbSession) -> DashboardStats:
    """Platform counts and service health."""
    return admin_service.dashboard(db)
