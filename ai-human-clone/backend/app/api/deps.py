from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_access_claims, issued_before
from app.db.session import get_db
from app.models import User
from app.services import monitoring, platform_service
from app.services.auth_service import get_active_user
from app.services.errors import MAINTENANCE, AuthenticationError, ForbiddenError, MaintenanceError

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    """Resolve the logged-in user from the HttpOnly session cookie, or raise 401/403."""
    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        raise AuthenticationError("Not authenticated")
    try:
        user_id, issued_at = decode_access_claims(token)
    except InvalidTokenError as exc:
        # Expired sessions are normal; anything else (bad signature, wrong algorithm,
        # garbage) is worth recording. The token itself is never logged.
        if "expired" not in str(exc).lower():
            monitoring.security("INVALID_TOKEN", "medium", request=request, details={"reason": type(exc.__cause__).__name__})
        raise AuthenticationError("Session expired or invalid, please log in again") from exc
    user = get_active_user(db, user_id)
    if issued_before(issued_at, user.sessions_valid_after):  # e.g. the password was changed since
        raise AuthenticationError("Session expired or invalid, please log in again")
    request.state.user_id = user.id  # for error and security records
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

ADMIN_REQUIRED = "Administrator access required."


def require_admin(request: Request, user: CurrentUser) -> User:
    """Every /api/admin route depends on this. is_admin comes from the database row,
    never from the token, the request or the browser."""
    if not user.is_admin:
        monitoring.security("ADMIN_ACCESS_DENIED", "high", request=request, user_id=user.id)
        raise ForbiddenError(ADMIN_REQUIRED)
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def session_user(db: Session, token: str | None) -> User | None:
    """The active user a session token belongs to, or None (invalid, expired, revoked, disabled)."""
    if not token:
        return None
    try:
        user_id, issued_at = decode_access_claims(token)
    except InvalidTokenError:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active or issued_before(issued_at, user.sessions_valid_after):
        return None
    return user


def _admin_from_cookie(request: Request, db: Session) -> bool:
    user = session_user(db, request.cookies.get(get_settings().auth_cookie_name))
    return bool(user and user.is_admin)


def maintenance_guard(request: Request, db: DbSession) -> None:
    """While maintenance mode is on, only administrators can use the app's APIs.
    (Admin, auth and health routes are outside this guard.)"""
    if platform_service.current(db).maintenance_mode and not _admin_from_cookie(request, db):
        raise MaintenanceError(MAINTENANCE)
