from __future__ import annotations

import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.teams import Organization, OrganizationAuditLog, OrganizationMember
from app.models.user import User
from app.org.schemas.org import OrganizationCreate, OrganizationRead, OrganizationUpdate, OwnershipTransfer
from app.org.services.notifications import ORG_NOTIFICATION_TYPES, create_notification
from app.org.services.rate_limit import org_creation_limit, ownership_transfer_limit

router = APIRouter()


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or secrets.token_hex(4)


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
@org_creation_limit
def create_organization(
    request: Request,
    payload: OrganizationCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    slug = slugify(payload.slug or payload.name)
    if db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{slug}-{secrets.token_hex(2)}"
    org = Organization(
        name=payload.name,
        slug=slug,
        description=payload.description,
        owner_id=current_user.id,
    )
    db.add(org)
    db.flush()
    mem = OrganizationMember(
        organization_id=org.id,
        user_id=current_user.id,
        role="owner",
        status="active",
    )
    db.add(mem)
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="organization_created",
            target_type="organization",
            target_id=str(org.id),
            metadata={"name": org.name},
        )
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=list[OrganizationRead])
def list_organizations(db=Depends(get_db), current_user=Depends(get_current_user)):
    org_ids = {m.organization_id for m in db.query(OrganizationMember).filter(OrganizationMember.user_id == current_user.id, OrganizationMember.status == "active").all()}
    q = db.query(Organization).filter(Organization.id.in_(org_ids) | (Organization.owner_id == current_user.id), Organization.is_active.is_(True))
    return q.order_by(Organization.created_at).all()


@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    if not (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    ) and not db.query(Organization).filter(Organization.id == organization_id, Organization.owner_id == current_user.id).first():
        raise HTTPException(status_code=403, detail="forbidden")
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    return org


@router.patch("/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
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
    if org.owner_id != current_user.id and not (mem and mem.role in ("owner", "admin")):
        raise HTTPException(status_code=403, detail="forbidden")
    if payload.name is not None:
        org.name = payload.name
    if payload.description is not None:
        org.description = payload.description
    if payload.slug is not None and slugify(payload.slug) != org.slug:
        slug = slugify(payload.slug)
        if db.query(Organization).filter(Organization.slug == slug).first():
            raise HTTPException(status_code=400, detail="slug_taken")
        org.slug = slug
    if payload.avatar_url is not None:
        org.avatar_url = payload.avatar_url
    if payload.is_active is not None and payload.is_active != org.is_active:
        # Deactivating (or reactivating) the organization is the owner's call.
        if org.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        org.is_active = payload.is_active
    db.add(org)
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="settings_changed",
            target_type="organization",
            target_id=str(org.id),
        )
    )
    db.commit()
    db.refresh(org)
    return org


@router.delete("/{organization_id}")
def delete_organization(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    org.is_active = False
    db.add(org)
    db.commit()
    return {"ok": True}


@router.post("/{organization_id}/transfer-ownership")
@ownership_transfer_limit
def transfer_ownership(
    request: Request,
    organization_id: uuid.UUID,
    payload: OwnershipTransfer,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm_required")
    target = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == payload.target_user_id,
        OrganizationMember.status == "active"
    ).first()
    if payload.target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="already_owner")
    if not target:
        raise HTTPException(status_code=400, detail="target_not_active_member")
    new_owner = db.get(User, payload.target_user_id)
    new_owner_name = new_owner.email if new_owner else str(payload.target_user_id)
    old_owner_mem = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == current_user.id
    ).first()
    if old_owner_mem:
        old_owner_mem.role = "admin"
        db.add(old_owner_mem)
    org.owner_id = payload.target_user_id
    target.role = "owner"
    db.add(target)
    db.add(org)
    db.add(OrganizationAuditLog(
        organization_id=org.id, actor_user_id=current_user.id,
        action="ownership_transferred", target_type="organization",
        target_id=str(org.id), metadata={"from": str(current_user.id), "to": str(payload.target_user_id)}
    ))
    # Notify new owner
    tpl = ORG_NOTIFICATION_TYPES["ownership_transferred"]
    create_notification(
        db,
        user_id=payload.target_user_id,
        type="ownership_transferred",
        title=tpl[0].format(org_name=org.name, user_name=new_owner_name),
        message=tpl[1].format(org_name=org.name, user_name=new_owner_name),
        organization_id=org.id,
        payload={"from_user": str(current_user.id), "to_user": str(payload.target_user_id)},
    )
    # Notify old owner
    create_notification(
        db,
        user_id=current_user.id,
        type="ownership_transferred",
        title="Ownership Transferred",
        message=f"You transferred ownership of {org.name} to {new_owner_name}",
        organization_id=org.id,
        payload={"from_user": str(current_user.id), "to_user": str(payload.target_user_id)},
    )
    db.commit()
    return {"ok": True}


@router.post("/{organization_id}/leave")
def leave_organization(
    organization_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    mem = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == current_user.id
    ).first()
    if not mem:
        raise HTTPException(status_code=404, detail="not_member")
    if mem.role == "owner" or org.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="owner_cannot_leave_transfer_first")
    mem.status = "removed"
    db.add(mem)
    db.add(OrganizationAuditLog(
        organization_id=org.id, actor_user_id=current_user.id,
        action="member_left", target_type="member",
        target_id=str(mem.id), metadata={"user_id": str(current_user.id)}
    ))
    # Notify organization owner
    if org.owner_id != current_user.id:
        tpl = ORG_NOTIFICATION_TYPES["member_left"]
        create_notification(
            db,
            user_id=org.owner_id,
            type="member_left",
            title=tpl[0].format(org_name=org.name, user_name=current_user.email),
            message=tpl[1].format(org_name=org.name, user_name=current_user.email),
            organization_id=org.id,
            payload={"user_id": str(current_user.id)},
        )
    db.commit()
    return {"ok": True}