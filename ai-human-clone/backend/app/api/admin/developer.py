"""Admin view of the developer platform (/api/admin/developer/*): API traffic, keys and
webhook health across all users. Key hashes and full keys are never returned; revoking
a key writes an admin audit log entry in the same transaction."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import and_, case, func, or_, select

from app.api.admin.common import PageLimit, PageNumber, Search
from app.api.deps import AdminUser, DbSession
from app.developer import keys_service
from app.developer.limits import plan_slug
from app.models import ApiKey, Organization, UsageEvent, User, WebhookDelivery, WebhookEndpoint
from app.schemas.admin import Page
from app.schemas.developer_dashboard import (
    AdminApiKeyRow,
    AdminDeveloperOverview,
    AdminEndpointRow,
    AdminKeyRevoke,
    AdminOrgUsageRow,
    AdminPlanUsageRow,
)
from app.services.admin_service import audit
from app.services.errors import NotFoundError

router = APIRouter(prefix="/developer")


def _like(text: str) -> str:
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _status_filter(status: str, now: datetime):
    not_expired = or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now)
    if status == "revoked":
        return ApiKey.revoked_at.is_not(None)
    if status == "expired":
        return and_(ApiKey.revoked_at.is_(None), ApiKey.expires_at.is_not(None), ApiKey.expires_at <= now)
    return and_(ApiKey.revoked_at.is_(None), not_expired)


def _count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/overview", response_model=AdminDeveloperOverview)
def overview(db: DbSession) -> AdminDeveloperOverview:
    now = datetime.now(UTC)
    day_ago, month_ago = now - timedelta(hours=24), now - timedelta(days=30)
    requests = UsageEvent.event_type == "API_REQUEST"
    is_error = func.sum(case((UsageEvent.status_code >= 400, 1), else_=0))

    top_endpoints = [
        AdminEndpointRow(endpoint=endpoint or "unknown", requests=n, errors=int(e or 0))
        for endpoint, n, e in db.execute(
            select(UsageEvent.endpoint, func.count(), is_error)
            .where(requests, UsageEvent.created_at >= month_ago)
            .group_by(UsageEvent.endpoint)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
    ]
    by_org = [
        AdminOrgUsageRow(organization_id=org_id, name=name, requests=n)
        for org_id, name, n in db.execute(
            select(UsageEvent.organization_id, Organization.name, func.count())
            .join(Organization, Organization.id == UsageEvent.organization_id)
            .where(requests, UsageEvent.created_at >= month_ago)
            .group_by(UsageEvent.organization_id, Organization.name)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
    ]
    # Plans are resolved per owner (cached for a minute in app.developer.limits).
    per_plan: dict[str, int] = {}
    owners = db.execute(
        select(UsageEvent.user_id, UsageEvent.organization_id, func.count())
        .where(requests, UsageEvent.created_at >= month_ago, UsageEvent.api_key_id.is_not(None))
        .group_by(UsageEvent.user_id, UsageEvent.organization_id)
    ).all()
    for user_id, org_id, n in owners:
        slug = plan_slug(db, user_id=None if org_id else user_id, organization_id=org_id)
        per_plan[slug] = per_plan.get(slug, 0) + n
    by_plan = [AdminPlanUsageRow(plan=slug, requests=n) for slug, n in sorted(per_plan.items(), key=lambda x: -x[1])]

    return AdminDeveloperOverview(
        api_requests_24h=_count(db, UsageEvent, requests, UsageEvent.created_at >= day_ago),
        api_requests_30d=_count(db, UsageEvent, requests, UsageEvent.created_at >= month_ago),
        active_keys=_count(db, ApiKey, _status_filter("active", now)),
        revoked_keys=_count(db, ApiKey, _status_filter("revoked", now)),
        expired_keys=_count(db, ApiKey, _status_filter("expired", now)),
        active_webhooks=_count(db, WebhookEndpoint, WebhookEndpoint.is_active.is_(True)),
        webhook_failures_24h=_count(
            db, WebhookDelivery, WebhookDelivery.status == "failed", WebhookDelivery.created_at >= day_ago
        ),
        rate_limit_events_24h=_count(
            db, UsageEvent, UsageEvent.event_type == "API_ERROR", UsageEvent.status_code == 429,
            UsageEvent.created_at >= day_ago,
        ),
        api_errors_24h=_count(db, UsageEvent, UsageEvent.event_type == "API_ERROR", UsageEvent.created_at >= day_ago),
        top_endpoints=top_endpoints,
        usage_by_organization=by_org,
        usage_by_plan=by_plan,
    )


def _row(key: ApiKey, email: str | None, org_name: str | None) -> AdminApiKeyRow:
    return AdminApiKeyRow(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=list(key.scopes or []),
        owner_type="organization" if key.organization_id else "user",
        owner=org_name if key.organization_id else email,
        user_id=key.user_id,
        organization_id=key.organization_id,
        status=keys_service.status_of(key),  # type: ignore[arg-type]
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@router.get("/keys", response_model=Page[AdminApiKeyRow])
def list_keys(
    db: DbSession,
    page: PageNumber = 1,
    limit: PageLimit = 20,
    search: Search = None,
    status: Literal["active", "revoked", "expired"] | None = None,
) -> Page[AdminApiKeyRow]:
    now = datetime.now(UTC)
    query = (
        select(ApiKey, User.email, Organization.name)
        .outerjoin(User, User.id == ApiKey.user_id)
        .outerjoin(Organization, Organization.id == ApiKey.organization_id)
    )
    if search and search.strip():
        pattern = _like(search)
        query = query.where(
            or_(
                func.lower(ApiKey.name).like(pattern, escape="\\"),
                func.lower(ApiKey.key_prefix).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"),
                func.lower(Organization.name).like(pattern, escape="\\"),
            )
        )
    if status:
        query = query.where(_status_filter(status, now))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(ApiKey.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    return Page(items=[_row(key, email, name) for key, email, name in rows], page=page, limit=limit, total=total)


@router.post("/keys/{key_id}/revoke", response_model=AdminApiKeyRow)
def revoke_key(
    key_id: uuid.UUID, admin: AdminUser, db: DbSession, data: AdminKeyRevoke | None = None
) -> AdminApiKeyRow:
    """Revoke any API key (abuse, leak). Recorded in the admin audit log."""
    key = db.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:  # revoking twice is a no-op, with no second audit entry
        details: dict = {"prefix": key.key_prefix, "before": keys_service.status_of(key), "after": "revoked"}
        if data is not None and data.reason and data.reason.strip():
            details["reason"] = data.reason.strip()
        # Added before revoke() so its commit stores the key change and the audit row together.
        audit(db, admin, "API_KEY_REVOKED", "api_key", key.id, details)
        keys_service.revoke(db, None, key)
    email = db.scalar(select(User.email).where(User.id == key.user_id)) if key.user_id else None
    org_name = db.scalar(select(Organization.name).where(Organization.id == key.organization_id)) if key.organization_id else None
    return _row(key, email, org_name)
