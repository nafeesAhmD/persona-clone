"""Organization analytics - restricted by role."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analytics import AnalyticsEvent
from app.models.clone_profile import CloneProfile
from app.models.teams import Organization
from app.org.services.features import count_org_messages

router = APIRouter(prefix="/organizations/{organization_id}", tags=["organizations-analytics"])


def _check_org_access(db, user_id: uuid.UUID, organization_id: uuid.UUID, roles: set[str]) -> Organization:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    if org.owner_id == user_id:
        return org
    from app.models.teams import OrganizationMember
    mem = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user_id,
        OrganizationMember.status == "active",
        OrganizationMember.role.in_(roles)
    ).first()
    if not mem:
        raise HTTPException(status_code=403, detail="forbidden")
    return org


@router.get("/analytics/overview")
def org_analytics_overview(
    organization_id: uuid.UUID,
    days: int = 30,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Organization analytics overview (admin/owner)."""
    _check_org_access(db, current_user.id, organization_id, {"owner", "admin"})
    
    from app.models.clone_profile import CloneProfile
    from app.models.document import Document
    from app.models.teams import OrganizationMember
    
    since = datetime.now(UTC) - timedelta(days=days)
    
    member_count = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.status == "active"
    ).count()
    
    clones = db.query(CloneProfile).filter(CloneProfile.organization_id == organization_id).all()
    clone_ids = [c.id for c in clones]
    
    message_count = count_org_messages(db, organization_id, days=days)
    
    doc_count = 0
    if clone_ids:
        doc_count = db.query(Document).filter(Document.clone_id.in_(clone_ids)).count()
    
    # Analytics events
    events_count = 0
    if clone_ids:
        events_count = db.query(AnalyticsEvent).filter(
            AnalyticsEvent.clone_id.in_(clone_ids),
            AnalyticsEvent.created_at >= since
        ).count()
    
    return {
        "organization_id": str(organization_id),
        "period_days": days,
        "members": member_count,
        "clones": len(clones),
        "messages": message_count,
        "documents": doc_count,
        "analytics_events": events_count,
    }


@router.get("/analytics/clone/{clone_id}")
def org_clone_analytics(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    days: int = 30,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Analytics for a specific clone in the organization (editor/viewer/admin/owner)."""
    _check_org_access(db, current_user.id, organization_id, {"owner", "admin", "editor", "viewer"})
    
    clone = db.query(CloneProfile).filter(
        CloneProfile.id == clone_id,
        CloneProfile.organization_id == organization_id
    ).first()
    if not clone:
        raise HTTPException(status_code=404, detail="clone_not_found")
    
    since = datetime.now(UTC) - timedelta(days=days)
    
    from app.models.analytics import AnalyticsEvent
    from app.models.document import Document
    
    messages = count_org_messages(db, organization_id, days=days, clone_id=clone_id)
    
    docs = db.query(Document).filter(Document.clone_id == clone_id).count()
    
    events = db.query(AnalyticsEvent).filter(
        AnalyticsEvent.clone_id == clone_id,
        AnalyticsEvent.created_at >= since
    ).count()
    
    return {
        "clone_id": str(clone_id),
        "clone_name": clone.name,
        "period_days": days,
        "messages": messages,
        "documents": docs,
        "analytics_events": events,
    }