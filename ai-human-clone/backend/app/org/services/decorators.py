"""Feature access decorators for organization-level checks (work on sync and async routes)."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from fastapi import HTTPException, status

from app.org.services.features import check_org_feature, check_org_limit
from app.org.services.route_guard import guard


def _org_context(kwargs: dict[str, Any]):
    db = kwargs.get("db")
    current_user = kwargs.get("current_user")
    organization_id = kwargs.get("organization_id")
    if db is None or current_user is None or organization_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_context")
    if not isinstance(organization_id, uuid.UUID):
        try:
            organization_id = uuid.UUID(str(organization_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_org_id") from None
    return db, organization_id


def require_org_feature(feature: str) -> Callable:
    """Decorator to require an organization-level feature."""

    def check(kwargs: dict[str, Any]) -> None:
        db, organization_id = _org_context(kwargs)
        if not check_org_feature(db, organization_id, feature):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"feature_not_enabled: {feature}")

    def decorator(func: Callable) -> Callable:
        return guard(func, check)

    return decorator


def require_org_limit(limit: str) -> Callable:
    """Decorator to require an organization-level limit not exceeded."""

    def check(kwargs: dict[str, Any]) -> None:
        db, organization_id = _org_context(kwargs)
        within, current, limit_val = check_org_limit(db, organization_id, limit)
        if not within:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Organization limit reached: {limit} ({current}/{limit_val}).",
            )

    def decorator(func: Callable) -> Callable:
        return guard(func, check)

    return decorator
