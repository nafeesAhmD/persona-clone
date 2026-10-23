import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Argon2id with the library's recommended parameters.
_hasher = PasswordHasher()

# Hash of a random password: verified against when an email doesn't exist so a
# failed login takes the same time either way (no user enumeration by timing).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class InvalidTokenError(Exception):
    """The access token is missing, malformed, expired or signed with another key."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    """Check a password against its hash. Pass None for an unknown user to keep timing constant."""
    if hashed_password is None:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return False
    try:
        return _hasher.verify(hashed_password, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    """True when the stored hash uses older parameters and should be upgraded on login."""
    try:
        return _hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return False


@lru_cache
def _secret_key() -> str:
    settings = get_settings()
    if settings.jwt_secret_key:
        return settings.jwt_secret_key
    if settings.environment.lower() == "production":
        raise RuntimeError("JWT_SECRET_KEY must be set in production")
    # Development fallback: sessions end whenever the backend restarts.
    logger.warning("JWT_SECRET_KEY is not set; using a temporary key (logins reset on restart)")
    return secrets.token_urlsafe(64)


def issued_before(issued_at: int, valid_after: datetime | None) -> bool:
    """Whether a token issued at `issued_at` (seconds) predates the user's session cut-off."""
    if valid_after is None:
        return False
    if valid_after.tzinfo is None:  # SQLite returns naive datetimes
        valid_after = valid_after.replace(tzinfo=UTC)
    return issued_at < int(valid_after.timestamp())


def create_access_token(user_id: uuid.UUID, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime, "type": "access"}
    return jwt.encode(payload, _secret_key(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id in a valid access token, or raise InvalidTokenError."""
    return decode_access_claims(token)[0]


def decode_access_claims(token: str) -> tuple[uuid.UUID, int]:
    """(user id, issued-at in whole seconds) of a valid access token, or raise InvalidTokenError."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            _secret_key(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
        if payload.get("type") != "access":
            raise InvalidTokenError("Wrong token type")
        return uuid.UUID(payload["sub"]), int(payload["iat"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
