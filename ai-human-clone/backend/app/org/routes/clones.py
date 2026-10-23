"""Clones assigned to an organization (CloneProfile.organization_id) and per-clone shares.

A clone joins an organization when its owner, an organization owner/admin, assigns it.
Members then reach it through the organization routes (knowledge, memories, analytics)
with their organization role; organization API keys (Phase 14) cover these clones too.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.clone_profile import CloneProfile
from app.models.teams import CloneMemberPermission, Organization, OrganizationAuditLog, OrganizationMember
from app.org.authz.permissions import has_organization_role
from app.org.schemas.org import CloneMemberPermissionRead, CloneMemberPermissionUpdate, OrganizationCloneRead
from app.org.services.features import check_org_limit

router = APIRouter()

ALL_ROLES = {"owner", "admin", "editor", "viewer"}
MANAGERS = {"owner", "admin"}


def _org_for(db, organization_id: uuid.UUID, user_id: uuid.UUID, roles: set[str]) -> Organization:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    ok, _ = has_organization_role(db, user_id, organization_id, roles)
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    return org


def _audit(db, org: Organization, actor_id: uuid.UUID, action: str, clone_id: uuid.UUID, **metadata) -> None:
    db.add(
        OrganizationAuditLog(
            organization_id=org.id,
            actor_user_id=actor_id,
            action=action,
            target_type="clone",
            target_id=str(clone_id),
            metadata={k: str(v) for k, v in metadata.items()},
        )
    )


@router.get("/{organization_id}/clones", response_model=list[OrganizationCloneRead])
def list_org_clones(organization_id: uuid.UUID, db=Depends(get_db), current_user=Depends(get_current_user)):
    """Clones assigned to the organization (any active member)."""
    _org_for(db, organization_id, current_user.id, ALL_ROLES)
    return (
        db.query(CloneProfile)
        .filter(CloneProfile.organization_id == organization_id)
        .order_by(CloneProfile.created_at)
        .all()
    )


@router.post("/{organization_id}/clones/{clone_id}", response_model=OrganizationCloneRead)
def assign_clone(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Assign one of your clones to the organization (you must be its owner or an admin)."""
    org = _org_for(db, organization_id, current_user.id, MANAGERS)
    if not org.is_active:
        raise HTTPException(status_code=400, detail="organization_inactive")
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone or clone.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="clone_not_found")
    if clone.organization_id == organization_id:
        return clone
    if clone.organization_id is not None:
        raise HTTPException(status_code=400, detail="clone_in_another_organization")
    within, _, _ = check_org_limit(db, organization_id, "max_clones")
    if not within:
        raise HTTPException(status_code=403, detail="org_clone_limit_reached")
    clone.organization_id = organization_id
    db.add(clone)
    _audit(db, org, current_user.id, "clone_assigned", clone.id)
    db.commit()
    db.refresh(clone)
    return clone


@router.delete("/{organization_id}/clones/{clone_id}")
def unassign_clone(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Take a clone out of the organization (its owner, or an organization owner/admin)."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="not_found")
    clone = (
        db.query(CloneProfile)
        .filter(CloneProfile.id == clone_id, CloneProfile.organization_id == organization_id)
        .first()
    )
    if not clone:
        raise HTTPException(status_code=404, detail="clone_not_found")
    manager, _ = has_organization_role(db, current_user.id, organization_id, MANAGERS)
    if clone.owner_id != current_user.id and not manager:
        raise HTTPException(status_code=403, detail="forbidden")
    clone.organization_id = None
    db.add(clone)
    # Per-clone shares only make sense inside the organization.
    db.query(CloneMemberPermission).filter(CloneMemberPermission.clone_id == clone_id).delete()
    _audit(db, org, current_user.id, "clone_unassigned", clone.id)
    db.commit()
    return {"ok": True}


@router.post("/{organization_id}/clones/{clone_id}/share", response_model=CloneMemberPermissionRead)
def share_clone(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CloneMemberPermissionUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Give one member a per-clone role on an organization clone (owner/admin)."""
    org = _org_for(db, organization_id, current_user.id, MANAGERS)
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone or clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="invalid_clone")
    target = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=400, detail="target_not_active_member")
    perm = (
        db.query(CloneMemberPermission)
        .filter(CloneMemberPermission.clone_id == clone_id, CloneMemberPermission.user_id == user_id)
        .first()
    )
    if not perm:
        perm = CloneMemberPermission(clone_id=clone_id, user_id=user_id, role=payload.role)
    else:
        perm.role = payload.role
    db.add(perm)
    _audit(db, org, current_user.id, "clone_shared", clone_id, user_id=user_id, role=payload.role)
    db.commit()
    db.refresh(perm)
    return perm


@router.delete("/{organization_id}/clones/{clone_id}/share/{user_id}")
def unshare_clone(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    user_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    org = _org_for(db, organization_id, current_user.id, MANAGERS)
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone or clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="invalid_clone")
    perm = (
        db.query(CloneMemberPermission)
        .filter(CloneMemberPermission.clone_id == clone_id, CloneMemberPermission.user_id == user_id)
        .first()
    )
    if perm:
        db.delete(perm)
    _audit(db, org, current_user.id, "clone_unshared", clone_id, user_id=user_id)
    db.commit()
    return {"ok": True}
