from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.teams import Organization, OrganizationAuditLog, OrganizationMember
from app.models.user import User
from app.org.schemas.org import OrganizationMemberRead, OrganizationMemberUpdate
from app.org.services.notifications import ORG_NOTIFICATION_TYPES, create_notification
from app.org.services.rate_limit import member_change_limit

router = APIRouter()


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberRead])
def list_members(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    if not (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    ):
        raise HTTPException(status_code=403, detail="forbidden")
    rows = (
        db.query(OrganizationMember, User)
        .outerjoin(User, User.id == OrganizationMember.user_id)
        .filter(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.joined_at)
        .all()
    )
    # A member's e-mail and name are only shown while they are active. Removed and
    # suspended members stay as rows (so the owner/admin can still act on the id),
    # but their personal details are not handed to other members, including viewers.
    return [
        OrganizationMemberRead.model_validate(member).model_copy(
            update={
                "email": user.email if user and member.status == "active" else None,
                "full_name": user.full_name if user and member.status == "active" else None,
            }
        )
        for member, user in rows
    ]


@router.patch("/{organization_id}/members/{member_id}", response_model=OrganizationMemberRead)
@member_change_limit
def update_member(
    request: Request,
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: OrganizationMemberUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    actor = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    )
    is_owner = org.owner_id == current_user.id and actor is not None
    if not is_owner and not (actor and actor.role == "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    mem = db.query(OrganizationMember).filter(OrganizationMember.id == member_id, OrganizationMember.organization_id == organization_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="not_found")
    # cannot modify owner via member record except ownership transfer
    if mem.role == "owner" or mem.user_id == org.owner_id:
        raise HTTPException(status_code=400, detail="cannot_modify_owner")
    # Only the owner manages admins (an admin can't promote to, or change, an admin).
    if not is_owner and (mem.role == "admin" or payload.role == "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    if payload.role is not None:
        old_role = mem.role
        mem.role = payload.role
        # Notify member of role change
        if old_role != mem.role:
            tpl = ORG_NOTIFICATION_TYPES["role_changed"]
            create_notification(
                db,
                user_id=mem.user_id,
                type="role_changed",
                title=tpl[0].format(org_name=org.name, role=mem.role),
                message=tpl[1].format(org_name=org.name, role=mem.role),
                organization_id=org.id,
                payload={"old_role": old_role, "new_role": mem.role, "changed_by": str(current_user.id)},
            )
    if payload.status is not None:
        mem.status = payload.status
    db.add(mem)
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="role_changed" if payload.role else "member_updated",
            target_type="member",
            target_id=str(mem.id),
            metadata={"user_id": str(mem.user_id)},
        )
    )
    db.commit()
    db.refresh(mem)
    return mem


@router.delete("/{organization_id}/members/{member_id}")
@member_change_limit
def remove_member(
    request: Request,
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    actor = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    )
    is_owner = org.owner_id == current_user.id and actor is not None
    if not is_owner and not (actor and actor.role == "admin"):
        raise HTTPException(status_code=403, detail="forbidden")
    mem = db.query(OrganizationMember).filter(OrganizationMember.id == member_id, OrganizationMember.organization_id == organization_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="not_found")
    if mem.role == "owner" or mem.user_id == org.owner_id:
        raise HTTPException(status_code=400, detail="cannot_remove_owner")
    if not is_owner and mem.role == "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    mem.status = "removed"
    db.add(mem)
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="member_removed",
            target_type="member",
            target_id=str(mem.id),
            metadata={"user_id": str(mem.user_id)},
        )
    )
    # Notify removed member
    removed_user = db.get(User, mem.user_id)
    user_name = removed_user.email if removed_user else "A member"
    tpl = ORG_NOTIFICATION_TYPES["member_removed"]
    create_notification(
        db,
        user_id=mem.user_id,
        type="member_removed",
        title=tpl[0].format(org_name=org.name, user_name=user_name),
        message=tpl[1].format(org_name=org.name, user_name=user_name),
        organization_id=org.id,
        payload={"removed_by": str(current_user.id)},
    )
    db.commit()
    return {"ok": True}
