"""API-key authentication for /api/v1 (separate from the browser's cookie sessions).

Canonical header:  Authorization: Bearer ahc_live_...
A request is accepted only if the key exists (by its keyed hash), isn't revoked or
expired, its owner (user or organization) is active, it is within its rate limits
and the plan's monthly API requests, and it has the scopes the endpoint needs.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.developer import limits, rate_limit
from app.developer.errors import ApiError
from app.developer.secrets import hash_api_key, looks_like_api_key
from app.models import ApiKey, Organization, User
from app.services import monitoring

bearer = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKeyAuth",
    description="Your API key: `Authorization: Bearer ahc_live_...`. Create one at /developer/keys.",
)
_LAST_USED_EVERY = timedelta(seconds=60)


@dataclass(frozen=True)
class ApiPrincipal:
    key_id: uuid.UUID
    key_name: str
    user_id: uuid.UUID | None  # personal key
    organization_id: uuid.UUID | None  # organization key
    scopes: frozenset[str]
    rate_limit_per_minute: int

    def has(self, scope: str) -> bool:
        return scope in self.scopes


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _reject(request: Request, message: str, reason: str) -> ApiError:
    monitoring.security("API_KEY_REJECTED", "medium", request=request, details={"reason": reason}, dedupe=True)
    return ApiError(401, "authentication_failed", message)


def get_api_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ApiPrincipal:
    if credentials is None or not looks_like_api_key(credentials.credentials):
        raise _reject(request, "Missing or invalid API key. Send `Authorization: Bearer <key>`.", "missing")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(credentials.credentials)))
    if key is None:
        raise _reject(request, "Invalid API key.", "unknown")
    now = datetime.now(UTC)
    if key.revoked_at is not None:
        raise _reject(request, "This API key has been revoked.", "revoked")
    if key.expires_at is not None and _aware(key.expires_at) <= now:
        raise _reject(request, "This API key has expired.", "expired")
    if key.organization_id is not None:
        org = db.get(Organization, key.organization_id)
        if org is None or not org.is_active:
            raise ApiError(403, "permission_denied", "The organization that owns this key is inactive.")
    else:
        user = db.get(User, key.user_id)
        if user is None or not user.is_active:
            raise ApiError(403, "permission_denied", "The account that owns this key is disabled.")

    # From here on, usage and errors are attributed to this key.
    request.state.api_key_id = key.id
    request.state.api_owner_user_id = key.user_id
    request.state.api_organization_id = key.organization_id
    if key.user_id:
        request.state.user_id = key.user_id

    allowed = limits.rate_limits(db, user_id=key.user_id, organization_id=key.organization_id)
    allowance = rate_limit.check(str(key.id), allowed)
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(allowance.limit),
        "X-RateLimit-Remaining": str(allowance.remaining),
        "X-RateLimit-Reset": str(allowance.reset_seconds),
    }
    limits.check_api_requests(db, user_id=key.user_id, organization_id=key.organization_id)

    if key.last_used_at is None or now - _aware(key.last_used_at) > _LAST_USED_EVERY:
        key.last_used_at = now
        db.commit()
    return ApiPrincipal(
        key_id=key.id,
        key_name=key.name,
        user_id=key.user_id,
        organization_id=key.organization_id,
        scopes=frozenset(key.scopes or []),
        rate_limit_per_minute=allowed.per_minute,
    )


ApiAuth = Annotated[ApiPrincipal, Depends(get_api_principal)]


def require_scope(*needed: str):
    """Dependency: the key must have every scope in `needed`."""

    def checker(principal: ApiAuth) -> ApiPrincipal:
        missing = [scope for scope in needed if not principal.has(scope)]
        if missing:
            raise ApiError(403, "permission_denied", f"This API key is missing the scope: {', '.join(missing)}.")
        return principal

    return checker


def Scoped(*needed: str):  # noqa: N802 - reads like a type in route signatures
    return Annotated[ApiPrincipal, Depends(require_scope(*needed))]
