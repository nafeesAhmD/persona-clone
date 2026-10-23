from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.billing import Plan
from app.models.teams import Organization, OrganizationMember, OrganizationSubscription
from app.org.services.features import get_org_features

router = APIRouter()


class OrgSubscriptionRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str
    plan_slug: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/{organization_id}/subscription", response_model=OrgSubscriptionRead)
def get_organization_subscription(
    organization_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    mem = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == current_user.id,
        OrganizationMember.status == "active"
    ).first()
    if org.owner_id != current_user.id and not mem:
        raise HTTPException(status_code=403, detail="forbidden")

    sub = db.query(OrganizationSubscription).filter(
        OrganizationSubscription.organization_id == organization_id,
        OrganizationSubscription.status == "active"
    ).first()
    if not sub:
        # Return free plan
        free_plan = db.query(Plan).filter(Plan.slug == "free").first()
        return {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "plan_id": free_plan.id if free_plan else uuid.uuid4(),
            "plan_name": "Free",
            "plan_slug": "free",
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    return {
        "id": sub.id,
        "organization_id": organization_id,
        "plan_id": sub.plan_id,
        "plan_name": plan.name if plan else "Unknown",
        "plan_slug": plan.slug if plan else "unknown",
        "status": sub.status,
        "created_at": sub.created_at,
        "updated_at": sub.updated_at,
    }


@router.get("/{organization_id}/features")
def get_organization_features(
    organization_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    mem = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == current_user.id,
        OrganizationMember.status == "active"
    ).first()
    if org.owner_id != current_user.id and not mem:
        raise HTTPException(status_code=403, detail="forbidden")

    features = get_org_features(db, organization_id)
    return features