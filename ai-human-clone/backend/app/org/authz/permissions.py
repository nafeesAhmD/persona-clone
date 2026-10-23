from __future__ import annotations

import uuid
from typing import Any, Callable

from fastapi import HTTPException, status

from app.models.clone_profile import CloneProfile
from app.models.teams import (
    CloneMemberPermission,
    Organization,
    OrganizationMember,
)
from app.org.services.route_guard import guard

# Higher rank includes everything a lower rank may do.
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


def _satisfies(role: str | None, roles: set[str]) -> bool:
    """`role` is one of `roles`, or ranks above the lowest of them."""
    if role is None or not roles:
        return False
    if role in roles:
        return True
    needed = min(ROLE_RANK.get(r, 99) for r in roles)
    return ROLE_RANK.get(role, 0) >= needed


def _active_member(db, user_id: uuid.UUID, organization_id: uuid.UUID) -> OrganizationMember | None:
    return (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
        .first()
    )


def organization_role(db, user_id: uuid.UUID, organization_id: uuid.UUID) -> str | None:
    """The user's role in an active organization, or None (no active membership)."""
    org = db.query(Organization).filter(Organization.id == organization_id, Organization.is_active.is_(True)).first()
    if not org:
        return None
    member = _active_member(db, user_id, organization_id)
    if not member:
        return None
    return "owner" if org.owner_id == user_id else member.role


def has_organization_role(db, user_id: uuid.UUID, organization_id: uuid.UUID, roles: set[str]) -> tuple[bool, str | None]:
    """Exact role match (the owner passes every check). Needs an active membership row."""
    role = organization_role(db, user_id, organization_id)
    if role is None:
        return False, None
    if role == "owner" or role in roles:
        return True, role
    return False, role


def has_clone_role(db, user_id: uuid.UUID, clone_id: uuid.UUID, roles: set[str]) -> tuple[bool, str | None]:
    """Clone owner always passes; otherwise the best of the user's org role (for a clone
    assigned to an organization) and any per-clone share, ranked owner > admin > editor > viewer."""
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone:
        return False, None
    if clone.owner_id == user_id:
        return True, "owner"
    candidates: list[str] = []
    if clone.organization_id:
        org_role = organization_role(db, user_id, clone.organization_id)
        if org_role is not None:
            candidates.append(org_role)
            perm = (
                db.query(CloneMemberPermission)
                .filter(CloneMemberPermission.clone_id == clone_id, CloneMemberPermission.user_id == user_id)
                .first()
            )
            if perm:
                candidates.append(perm.role)
    if not candidates:
        return False, None
    best = max(candidates, key=lambda r: ROLE_RANK.get(r, 0))
    return _satisfies(best, roles), best


def _as_uuid(value: Any, detail: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from None


def _context(kwargs: dict[str, Any], id_name: str):
    db = kwargs.get("db")
    current_user = kwargs.get("current_user")
    target = kwargs.get(id_name)
    if db is None or current_user is None or target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_context")
    return db, current_user, _as_uuid(target, f"invalid_{id_name}")


def require_organization_member(roles: set[str] | None = None) -> Callable:
    """Decorator for routes taking `organization_id`, `db` and `current_user` (sync or async)."""
    allowed = roles or {"owner", "admin", "editor", "viewer"}

    def check(kwargs: dict[str, Any]) -> None:
        db, current_user, org_id = _context(kwargs, "organization_id")
        ok, _ = has_organization_role(db, current_user.id, org_id, allowed)
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    def decorator(func: Callable) -> Callable:
        return guard(func, check)

    return decorator


def require_organization_admin() -> Callable:
    return require_organization_member({"owner", "admin"})


def require_organization_editor() -> Callable:
    return require_organization_member({"owner", "admin", "editor"})


def require_organization_owner() -> Callable:
    return require_organization_member({"owner"})


def _require_clone(roles: set[str]) -> Callable:
    """Decorator for routes taking `clone_id`, `db` and `current_user` (sync or async)."""

    def check(kwargs: dict[str, Any]) -> None:
        db, current_user, clone_id = _context(kwargs, "clone_id")
        ok, _ = has_clone_role(db, current_user.id, clone_id, roles)
        if not ok:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    def decorator(func: Callable) -> Callable:
        return guard(func, check)

    return decorator


def require_clone_access() -> Callable:
    return _require_clone({"viewer"})


def require_clone_editor() -> Callable:
    return _require_clone({"editor"})


def require_clone_owner() -> Callable:
    return _require_clone({"owner"})
