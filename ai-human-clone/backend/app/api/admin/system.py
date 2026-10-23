from datetime import date

from fastapi import APIRouter, Query

from app.api.admin.common import PageLimit, PageNumber
from app.api.deps import DbSession
from app.schemas.admin import ErrorEventRow, Page, SystemHealth
from app.services import admin_service

router = APIRouter(prefix="/system")


@router.get("/health", response_model=SystemHealth)
def health() -> SystemHealth:
    """Status of each service; no hosts, keys or raw errors."""
    return admin_service.system_health()


@router.get("/errors", response_model=Page[ErrorEventRow])
def errors(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    category: str | None = Query(default=None, max_length=30),
    status_code: int | None = Query(default=None, ge=100, le=599),
    endpoint: str | None = Query(default=None, max_length=100),
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[ErrorEventRow]:
    return admin_service.error_events(
        db, page=page, limit=limit, category=category, status_code=status_code,
        endpoint=endpoint, date_from=date_from, date_to=date_to,
    )
