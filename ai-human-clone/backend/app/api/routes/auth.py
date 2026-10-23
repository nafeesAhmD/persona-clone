from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, UserRead
from app.services import auth_service, monitoring, platform_service
from app.services.errors import AuthenticationError, ForbiddenError
from app.services.rate_limit import check_login_rate

REGISTRATION_CLOSED = "New registrations are currently closed."

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    """Issue a fresh access token in an HttpOnly cookie that browser JavaScript can't read."""
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=create_access_token(user.id),
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, response: Response, db: DbSession) -> UserRead:
    """Create an account and start a session straight away (unless registration is closed)."""
    settings = platform_service.current(db)
    if not settings.public_registration_enabled or settings.maintenance_mode:
        raise ForbiddenError(REGISTRATION_CLOSED)
    user = auth_service.register_user(db, data)
    _set_session_cookie(response, user)
    return UserRead.model_validate(user)


@router.post("/login", response_model=UserRead)
def login(data: LoginRequest, request: Request, response: Response, db: DbSession) -> UserRead:
    """Rate limited per address and email; repeated failures lock the account for a few minutes."""
    check_login_rate(monitoring.client_ip(request), data.email)
    try:
        user = auth_service.authenticate(db, data.email, data.password)
    except AuthenticationError:
        # The email itself isn't stored; the account id is, when the email belongs to one.
        known = auth_service.user_id_for_email(db, data.email)
        monitoring.security("LOGIN_FAILED", "medium", request=request, user_id=known)
        raise
    except auth_service.AccountLockedError:
        monitoring.security("LOGIN_LOCKED", "high", request=request, user_id=auth_service.user_id_for_email(db, data.email))
        raise
    except ForbiddenError:
        monitoring.security("LOGIN_DISABLED_ACCOUNT", "medium", request=request, user_id=auth_service.user_id_for_email(db, data.email))
        raise
    monitoring.security("LOGIN_SUCCESS", "low", request=request, user_id=user.id)
    _set_session_cookie(response, user)
    return UserRead.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    # The token itself stays valid until it expires (stateless JWT); removing the
    # cookie ends the browser session. Server-side revocation is a later addition.
    _clear_session_cookie(response)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser, response: Response) -> UserRead:
    # Sliding session: each check renews the cookie, so active users stay logged in
    # while an idle session still ends after ACCESS_TOKEN_EXPIRE_MINUTES.
    _set_session_cookie(response, user)
    return UserRead.model_validate(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(data: ChangePasswordRequest, user: CurrentUser, response: Response, db: DbSession) -> None:
    auth_service.change_password(db, user, data)
    _set_session_cookie(response, user)
