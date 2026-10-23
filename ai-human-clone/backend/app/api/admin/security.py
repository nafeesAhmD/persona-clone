import uuid
from datetime import date

from fastapi import APIRouter, Query

from app.api.admin.common import PageLimit, PageNumber
from app.api.deps import DbSession
from app.schemas.admin import AuditLogRow, Page, SecurityEventRow
from app.services import admin_service

router = APIRouter()


@router.get("/security/events", response_model=Page[SecurityEventRow])
def security_events(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    event_type: str | None = Query(default=None, max_length=40),
    severity: str | None = Query(default=None, max_length=10),
    user_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[SecurityEventRow]:
    return admin_service.security_events(
        db, page=page, limit=limit, event_type=event_type, severity=severity,
        user_id=user_id, date_from=date_from, date_to=date_to,
    )


@router.get("/audit-logs", response_model=Page[AuditLogRow])
def audit_logs(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    action: str | None = Query(default=None, max_length=60),
    admin_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[AuditLogRow]:
    return admin_service.audit_logs(
        db, page=page, limit=limit, action=action, admin_id=admin_id, date_from=date_from, date_to=date_to
    )
