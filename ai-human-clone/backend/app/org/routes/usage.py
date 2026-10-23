from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.billing import Plan
from app.models.clone_profile import CloneProfile
from app.models.document import Document
from app.models.teams import Organization, OrganizationMember
from app.org.services.features import count_org_messages, get_org_features, get_org_limits, get_org_plan_name

router = APIRouter()


class OrgUsageRead(BaseModel):
    plan_name: str
    plan_slug: str
    members: dict
    clones: dict
    messages: dict
    documents: dict
    features: dict
    limits: dict


@router.get("/{organization_id}/usage", response_model=OrgUsageRead)
def get_org_usage(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    """Current usage against the organization's plan limits (any active member)."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    mem = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    )
    if not mem:
        raise HTTPException(status_code=403, detail="forbidden")

    plan_slug = get_org_plan_name(db, organization_id)
    plan = db.query(Plan).filter(Plan.slug == plan_slug).first()
    limits = get_org_limits(db, organization_id)

    members = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == organization_id, OrganizationMember.status == "active")
        .count()
    )
    clones = db.query(CloneProfile).filter(CloneProfile.organization_id == organization_id).count()
    documents = (
        db.query(Document)
        .join(CloneProfile, Document.clone_id == CloneProfile.id)
        .filter(CloneProfile.organization_id == organization_id)
        .count()
    )
    return {
        "plan_name": plan.name if plan else plan_slug.title(),
        "plan_slug": plan_slug,
        "members": {"used": members, "limit": limits.get("max_members")},
        "clones": {"used": clones, "limit": limits.get("max_clones")},
        "messages": {"used": count_org_messages(db, organization_id, days=30), "limit": limits.get("monthly_messages")},
        "documents": {"used": documents, "limit": None},
        "features": get_org_features(db, organization_id),
        "limits": limits,
    }
