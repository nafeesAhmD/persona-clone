from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.teams import Organization, OrganizationAuditLog, OrganizationInvitation, OrganizationMember
from app.models.user import User
from app.org.authz.permissions import has_organization_role
from app.org.schemas.org import OrganizationInvitationCreate, OrganizationInvitationCreated, OrganizationInvitationRead
from app.org.services.invitation import create_invitation, find_pending
from app.org.services.notifications import ORG_NOTIFICATION_TYPES, create_notification
from app.org.services.rate_limit import invitation_accept_limit, invitation_send_limit

router = APIRouter()

MANAGERS = {"owner", "admin"}


def _managed_org(db, organization_id: uuid.UUID, user_id: uuid.UUID) -> Organization:
    """The organization, if the user is its owner or an admin (active membership)."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    ok, _ = has_organization_role(db, user_id, organization_id, MANAGERS)
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    return org


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=OrganizationInvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
@invitation_send_limit
def create_invitation_route(
    request: Request,
    organization_id: uuid.UUID,
    payload: OrganizationInvitationCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Invite someone by e-mail (owner/admin). The token in the reply is shown only once."""
    org = _managed_org(db, organization_id, current_user.id)
    email = payload.email.lower()
    invited_user = db.query(User).filter(User.email == email).first()
    if invited_user and (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == invited_user.id,
            OrganizationMember.status == "active",
        )
        .first()
    ):
        raise HTTPException(status_code=400, detail="already_member")
    res = create_invitation(db, organization_id, email, current_user.id, payload.role)
    if not res:
        raise HTTPException(status_code=400, detail="duplicate_pending")
    inv, token = res
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=current_user.id,
            action="member_invited",
            target_type="invitation",
            target_id=str(inv.id),
            metadata={"email": email, "role": payload.role},
        )
    )
    if invited_user:
        tpl = ORG_NOTIFICATION_TYPES["invitation_received"]
        create_notification(
            db,
            user_id=invited_user.id,
            type="invitation_received",
            title=tpl[0].format(org_name=org.name, role=payload.role),
            message=tpl[1].format(org_name=org.name, role=payload.role),
            organization_id=org.id,
            payload={"invitation_id": str(inv.id), "role": payload.role},
        )
    db.commit()
    db.refresh(inv)
    return OrganizationInvitationCreated(**OrganizationInvitationRead.model_validate(inv).model_dump(), token=token)


@router.get("/organizations/{organization_id}/invitations", response_model=list[OrganizationInvitationRead])
def list_invitations(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    _managed_org(db, organization_id, current_user.id)
    return (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.organization_id == organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
        .all()
    )


@router.delete("/organizations/{organization_id}/invitations/{invitation_id}")
def cancel_invitation(
    organization_id: uuid.UUID,
    invitation_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = _managed_org(db, organization_id, current_user.id)
    inv = (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.id == invitation_id, OrganizationInvitation.organization_id == organization_id)
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="not_found")
    if inv.status == "pending":
        inv.status = "cancelled"
        db.add(inv)
        db.add(
            OrganizationAuditLog(
                organization_id=org.id,
                actor_user_id=current_user.id,
                action="invitation_cancelled",
                target_type="invitation",
                target_id=str(inv.id),
            )
        )
        db.commit()
    return {"ok": True}


def _invitation_for(db, token: str, current_user) -> OrganizationInvitation:
    """A live invitation addressed to the signed-in user's e-mail, in an active organization."""
    inv = find_pending(db, token)
    if not inv:
        raise HTTPException(status_code=400, detail="invalid_or_expired")
    if inv.email.lower() != current_user.email.lower():
        raise HTTPException(status_code=403, detail="invitation_for_another_email")
    org = db.query(Organization).filter(Organization.id == inv.organization_id, Organization.is_active.is_(True)).first()
    if not org:
        raise HTTPException(status_code=400, detail="invalid_or_expired")
    return inv


@router.post("/invitations/{token}/accept")
@invitation_accept_limit
def accept_invitation_route(
    request: Request,
    token: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Join the organization. Only the account with the invited e-mail can accept."""
    inv = _invitation_for(db, token, current_user)
    org = db.query(Organization).filter(Organization.id == inv.organization_id).first()
    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == inv.organization_id,
            OrganizationMember.user_id == current_user.id,
        )
        .first()
    )
    if member and member.status == "active":
        raise HTTPException(status_code=400, detail="already_member")
    if member:
        # Rejoining after leaving or being removed: the invitation decides the role.
        member.status = "active"
        member.role = inv.role
    else:
        member = OrganizationMember(
            organization_id=inv.organization_id,
            user_id=current_user.id,
            role=inv.role,
            status="active",
        )
    db.add(member)
    inv.status = "accepted"
    inv.accepted_at = datetime.now(UTC)
    db.add(inv)
    db.add(
        OrganizationAuditLog(
            organization_id=inv.organization_id,
            actor_user_id=current_user.id,
            action="member_joined",
            target_type="invitation",
            target_id=str(inv.id),
            metadata={"role": inv.role},
        )
    )
    if org.owner_id != current_user.id:
        tpl = ORG_NOTIFICATION_TYPES["invitation_accepted"]
        create_notification(
            db,
            user_id=org.owner_id,
            type="invitation_accepted",
            title=tpl[0].format(org_name=org.name, user_name=current_user.email),
            message=tpl[1].format(org_name=org.name, user_name=current_user.email),
            organization_id=org.id,
            payload={"invitation_id": str(inv.id), "user_id": str(current_user.id)},
        )
    db.commit()
    return {"ok": True, "organization_id": str(org.id), "role": inv.role}


@router.post("/invitations/{token}/decline")
def decline_invitation_route(token: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    inv = _invitation_for(db, token, current_user)
    inv.status = "cancelled"
    db.add(inv)
    org = db.query(Organization).filter(Organization.id == inv.organization_id).first()
    if org.owner_id != current_user.id:
        create_notification(
            db,
            user_id=org.owner_id,
            type="invitation_declined",
            title="Invitation Declined",
            message=f"{current_user.email} declined your invitation to {org.name}",
            organization_id=org.id,
            payload={"invitation_id": str(inv.id), "user_id": str(current_user.id)},
        )
    db.commit()
    return {"ok": True}
