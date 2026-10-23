import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, password_needs_rehash, verify_password
from app.models import User
from app.schemas.auth import ChangePasswordRequest, RegisterRequest, UserUpdate
from app.services.errors import AuthenticationError, ConflictError, ForbiddenError, InvalidInputError

logger = logging.getLogger(__name__)

# One message for unknown email and wrong password, so accounts can't be probed.
INVALID_CREDENTIALS = "Invalid email or password"
LOCKED = "Too many failed login attempts. Please wait a few minutes and try again."


class AccountLockedError(Exception):
    """Temporarily locked after repeated failed logins (HTTP 429)."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _ensure_unique(
    db: Session,
    *,
    email: str | None = None,
    username: str | None = None,
    exclude: uuid.UUID | None = None,
) -> None:
    def taken(column, value) -> bool:
        query = select(User.id).where(column == value)
        if exclude is not None:
            query = query.where(User.id != exclude)
        return db.scalar(query) is not None

    if email is not None and taken(User.email, email):
        raise ConflictError("An account with this email already exists")
    if username is not None and taken(User.username, username):
        raise ConflictError("This username is already taken")


def _commit_unique(db: Session) -> None:
    # The checks above can race with a concurrent request; the unique indexes are the backstop.
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Email or username is already taken") from exc


def register_user(db: Session, data: RegisterRequest) -> User:
    _ensure_unique(db, email=data.email, username=data.username)
    user = User(
        email=data.email,
        username=data.username,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    _commit_unique(db)
    db.refresh(user)
    logger.info("Registered user %s", user.id)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Check credentials. After LOGIN_MAX_FAILED_ATTEMPTS failures in a row the account
    waits LOGIN_LOCKOUT_MINUTES (temporary, never permanent); success resets the count."""
    settings = get_settings()
    now = datetime.now(UTC)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.locked_until is not None and _aware(user.locked_until) > now:
        verify_password(password, None)  # keep timing similar
        raise AccountLockedError(LOCKED)
    if user is None or not verify_password(password, user.hashed_password):
        if user is None:
            verify_password(password, None)  # same work as a real check (timing)
        else:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                logger.warning("User %s locked for %d minutes after failed logins", user.id, settings.login_lockout_minutes)
            db.commit()
        raise AuthenticationError(INVALID_CREDENTIALS)
    if not user.is_active:
        raise ForbiddenError("This account is disabled")
    if user.failed_login_count or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()

    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
        db.commit()
    return user


def user_id_for_email(db: Session, email: str) -> uuid.UUID | None:
    return db.scalar(select(User.id).where(User.email == email))


def get_active_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Not authenticated")
    if not user.is_active:
        raise ForbiddenError("This account is disabled")
    return user


def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    changes = data.model_dump(exclude_unset=True)
    if "username" in changes and changes["username"] is None:
        del changes["username"]  # username can be changed but not removed
    if changes.get("username") and changes["username"] != user.username:
        _ensure_unique(db, username=changes["username"], exclude=user.id)

    for field, value in changes.items():
        setattr(user, field, value)
    _commit_unique(db)
    db.refresh(user)
    return user


def change_password(db: Session, user: User, data: ChangePasswordRequest) -> None:
    # 400, not 401: the session is fine, only the form input is wrong.
    if not verify_password(data.current_password, user.hashed_password):
        raise InvalidInputError("Current password is incorrect")
    if data.current_password == data.new_password:
        raise InvalidInputError("New password must be different from the current one")
    user.hashed_password = hash_password(data.new_password)
    # Sign out every other session; the route then issues this browser a fresh one.
    user.sessions_valid_after = datetime.now(UTC).replace(microsecond=0)
    db.commit()
    logger.info("Password changed for user %s; older sessions revoked", user.id)
