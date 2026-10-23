from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.admin import UsageReport
from app.services import admin_service

router = APIRouter()


@router.get("/usage", response_model=UsageReport)
def usage(db: DbSession, days: int = Query(default=7, ge=1, le=90)) -> UsageReport:
    """Aggregated usage. Costs only when prices are configured, and always labelled estimates."""
    return admin_service.usage_report(db, days=days)
