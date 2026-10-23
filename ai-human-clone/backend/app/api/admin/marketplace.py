"""Marketplace moderation (Phase 18): reports and per-clone suspension / featuring.
Every change is written to the admin audit log."""

import uuid

from fastapi import APIRouter, Query

from app.api.admin.common import PageLimit, PageNumber, Search
from app.api.deps import AdminUser, DbSession
from app.marketplace import service
from app.marketplace.schemas import (
    AdminCloneMarketplace,
    AdminCloneFilter,
    AdminCloneMarketplaceUpdate,
    AdminMarketplaceClonePage,
    AdminReport,
    AdminReportPage,
    AdminReportUpdate,
    ReportStatus,
)

router = APIRouter(prefix="/marketplace")


@router.get("/reports", response_model=AdminReportPage)
def list_reports(
    db: DbSession, page: PageNumber = 1, page_size: PageLimit = 20, status: ReportStatus | None = Query(default=None)
) -> AdminReportPage:
    return service.admin_reports(db, status=status, page=page, page_size=page_size)


@router.patch("/reports/{report_id}", response_model=AdminReport)
def update_report(report_id: uuid.UUID, data: AdminReportUpdate, admin: AdminUser, db: DbSession) -> AdminReport:
    return service.admin_update_report(db, admin, report_id, data)


@router.get("/clones", response_model=AdminMarketplaceClonePage)
def list_clones(
    db: DbSession,
    page: PageNumber = 1,
    page_size: PageLimit = 20,
    status: AdminCloneFilter = "all",
    q: Search = None,
) -> AdminMarketplaceClonePage:
    """Marketplace clones (opted in, suspended or featured), to manage without a report."""
    return service.admin_clones(db, status=status, q=q, page=page, page_size=page_size)


@router.patch("/clones/{clone_id}/visibility", response_model=AdminCloneMarketplace)
def update_clone(
    clone_id: uuid.UUID, data: AdminCloneMarketplaceUpdate, admin: AdminUser, db: DbSession
) -> AdminCloneMarketplace:
    """Suspend / unsuspend a clone from the marketplace (the clone itself stays) and set
    its featured rank (null = not featured)."""
    return service.admin_update_clone(db, admin, clone_id, data)
