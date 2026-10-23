"""Who may configure or run a clone's agent, and who may see an execution (Phase 16).

Roles come from the database (Phase 13 organizations), never from the request:

| who                                  | see profile | configure | run                         |
|--------------------------------------|-------------|-----------|-----------------------------|
| clone owner                          | yes         | yes       | yes                         |
| org owner / admin (clone in the org) | yes         | yes       | yes                         |
| org editor                           | yes         | no (403)  | yes                         |
| org viewer                           | yes         | no (403)  | only if allow_viewer_use    |
| anyone else                          | 404 for a private clone, 403 otherwise; never runs     |

Only the clone owner may toggle public_agent_enabled (checked in the route).

Executions are visible to the person who started them, the clone owner and the org
owner/admins of the clone's organization; everyone else gets 404 (no existence leaks).
Confirming/rejecting an action additionally needs run permission.
"""

import uuid

from sqlalchemy.orm import Session

from app.models import AgentExecution, AgentProfile, CloneProfile, User
from app.org.authz.permissions import has_clone_role, organization_role
from app.services.clone_service import NOT_FOUND
from app.services.errors import ForbiddenError, NotFoundError

CONFIGURE_DENIED = "Only the clone's owner or an organization admin can change the AI agent."
ANALYTICS_DENIED = "Only the clone's owner or an organization admin can see agent analytics."
RUN_DENIED = "You don't have permission to run this AI agent."
EXECUTION_NOT_FOUND = "Agent execution not found"
_ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


def clone_role(db: Session, user: User, clone: CloneProfile) -> str | None:
    """The user's effective role on the clone: "owner" for the clone owner, else the best
    of their organization role and per-clone share (only for clones in an organization)."""
    if clone.owner_id == user.id:
        return "owner"
    if not clone.organization_id:
        return None
    _, role = has_clone_role(db, user.id, clone.id, {"owner"})
    return role


def can_configure(db: Session, user: User, clone: CloneProfile) -> bool:
    return _ROLE_RANK.get(clone_role(db, user, clone) or "", 0) >= _ROLE_RANK["admin"]


def can_run(db: Session, user: User, clone: CloneProfile, profile: AgentProfile | None) -> bool:
    role = clone_role(db, user, clone)
    if role is None:
        return False
    if _ROLE_RANK.get(role, 0) >= _ROLE_RANK["editor"]:
        return True
    return role == "viewer" and bool(profile is not None and profile.allow_viewer_use)


def _find_visible_clone(db: Session, user: User, clone_id: uuid.UUID) -> tuple[CloneProfile, str | None]:
    """The clone and the user's role; 404 for missing clones and for private clones the
    user has no role on (same rule as clone_service.get_managed_clone)."""
    clone = db.get(CloneProfile, clone_id)
    if clone is None:
        raise NotFoundError(NOT_FOUND)
    role = clone_role(db, user, clone)
    if role is None and clone.visibility == "private":
        raise NotFoundError(NOT_FOUND)
    return clone, role


def require_view(db: Session, user: User, clone_id: uuid.UUID) -> CloneProfile:
    """Anyone with a role on the clone may see its agent settings (with can_* flags)."""
    clone, role = _find_visible_clone(db, user, clone_id)
    if role is None:
        raise ForbiddenError(RUN_DENIED)
    return clone


def require_configure(
    db: Session, user: User, clone_id: uuid.UUID, message: str = CONFIGURE_DENIED
) -> CloneProfile:
    clone, _ = _find_visible_clone(db, user, clone_id)
    if not can_configure(db, user, clone):
        raise ForbiddenError(message)
    return clone


def require_run(db: Session, user: User, clone_id: uuid.UUID, profile_of) -> tuple[CloneProfile, AgentProfile]:
    """`profile_of(clone)` returns (or creates) the clone's AgentProfile."""
    clone, role = _find_visible_clone(db, user, clone_id)
    if role is None:
        raise ForbiddenError(RUN_DENIED)
    profile = profile_of(clone)
    if not can_run(db, user, clone, profile):
        raise ForbiddenError(RUN_DENIED)
    return clone, profile


def can_view_execution(db: Session, user: User, execution: AgentExecution) -> bool:
    if execution.user_id is not None and execution.user_id == user.id:
        return True
    clone = db.get(CloneProfile, execution.clone_id)
    if clone is None:
        return False
    if clone.owner_id == user.id:
        return True
    if clone.organization_id:
        return organization_role(db, user.id, clone.organization_id) in ("owner", "admin")
    return False


def require_execution(db: Session, user: User, execution: AgentExecution | None) -> AgentExecution:
    if execution is None or not can_view_execution(db, user, execution):
        raise NotFoundError(EXECUTION_NOT_FOUND)
    return execution
