"""The developer dashboard for logged-in users: /api/developer/overview and /usage.

Counts only API-key calls (usage events that carry an api_key_id) of one owner: the
user's personal keys, or with ?organization_id= an organization the user manages.
Never returns a key, key hash or webhook secret.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.developer import keys_service
from app.developer.limits import monthly_api_requests, plan_limits, plan_slug, rate_limits
from app.models import ApiKey, UsageEvent, User, WebhookEndpoint
from app.schemas.developer_dashboard import (
    DeveloperOverview,
    DeveloperUsage,
    UsageByEndpoint,
    UsageByKey,
    UsagePerDay,
)
from app.services.errors import ForbiddenError

router = APIRouter(tags=["developer"])

OrgParam = Query(default=None, description="An organization you own or administer; omit for your personal keys.")


def _owner(db: Session, user: User, organization_id: uuid.UUID | None) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    if organization_id is None:
        return user.id, None
    if not keys_service.can_manage_org(db, user, organization_id):
        raise ForbiddenError("Only an organization's owner or admins can see its developer usage.")
    return None, organization_id


def _events(user_id: uuid.UUID | None, organization_id: uuid.UUID | None):
    """API-key usage events of one owner (deleted keys' history included)."""
    owner = (
        UsageEvent.organization_id == organization_id
        if organization_id
        else (UsageEvent.user_id == user_id) & UsageEvent.organization_id.is_(None)
    )
    return [UsageEvent.api_key_id.is_not(None), owner]


def _key_owner(model, user_id, organization_id):
    return model.organization_id == organization_id if organization_id else model.user_id == user_id


def _count(db: Session, *where) -> int:
    return db.scalar(select(func.count()).select_from(UsageEvent).where(*where)) or 0


@router.get("/overview", response_model=DeveloperOverview)
def overview(user: CurrentUser, db: DbSession, organization_id: uuid.UUID | None = OrgParam) -> DeveloperOverview:
    user_id, org_id = _owner(db, user, organization_id)
    scope = _events(user_id, org_id)
    since = datetime.now(UTC) - timedelta(days=30)
    requests = [*scope, UsageEvent.event_type == "API_REQUEST", UsageEvent.created_at >= since]
    slug = plan_slug(db, user_id=user_id, organization_id=org_id)
    keys = db.scalars(select(ApiKey).where(_key_owner(ApiKey, user_id, org_id))).all()
    active_keys = sum(1 for key in keys if keys_service.status_of(key) == "active")
    return DeveloperOverview(
        plan=slug,
        api_requests_30d=_count(db, *requests),
        chat_requests_30d=_count(db, *requests, UsageEvent.endpoint.like("%/chat")),
        successful_requests_30d=_count(db, *requests, UsageEvent.status_code < 400),
        failed_requests_30d=_count(db, *requests, UsageEvent.status_code >= 400),
        monthly_requests=monthly_api_requests(db, user_id=user_id, organization_id=org_id),
        monthly_limit=int(plan_limits(db, slug).get("api_requests", 0) or 0),
        rate_limit_per_minute=rate_limits(db, user_id=user_id, organization_id=org_id).per_minute,
        active_keys=active_keys,
        active_webhooks=db.scalar(
            select(func.count())
            .select_from(WebhookEndpoint)
            .where(_key_owner(WebhookEndpoint, user_id, org_id), WebhookEndpoint.is_active.is_(True))
        )
        or 0,
    )


@router.get("/usage", response_model=DeveloperUsage)
def usage(
    user: CurrentUser,
    db: DbSession,
    days: int = Query(default=30, ge=1, le=90),
    organization_id: uuid.UUID | None = OrgParam,
) -> DeveloperUsage:
    user_id, org_id = _owner(db, user, organization_id)
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(first_day, datetime.min.time(), UTC)
    where = [*_events(user_id, org_id), UsageEvent.event_type == "API_REQUEST", UsageEvent.created_at >= since]
    is_error = func.sum(case((UsageEvent.status_code >= 400, 1), else_=0))

    day = func.date(UsageEvent.created_at)
    found: dict[str, tuple[int, int]] = {
        str(d): (n, int(e or 0))
        for d, n, e in db.execute(select(day, func.count(), is_error).where(*where).group_by(day)).all()
    }
    per_day = []
    for offset in range(days):
        label = (first_day + timedelta(days=offset)).isoformat()
        requests, errors = found.get(label, (0, 0))
        per_day.append(UsagePerDay(day=label, requests=requests, errors=errors))

    by_endpoint = [
        UsageByEndpoint(
            endpoint=endpoint or "unknown",
            requests=n,
            errors=int(e or 0),
            avg_duration_ms=round(float(avg), 1) if avg is not None else None,
        )
        for endpoint, n, e, avg in db.execute(
            select(UsageEvent.endpoint, func.count(), is_error, func.avg(UsageEvent.duration_ms))
            .where(*where)
            .group_by(UsageEvent.endpoint)
            .order_by(func.count().desc())
            .limit(50)
        ).all()
    ]

    by_key = [
        UsageByKey(key_id=key_id, name=name or "(deleted key)", key_prefix=prefix or "", requests=n)
        for key_id, name, prefix, n in db.execute(
            select(UsageEvent.api_key_id, ApiKey.name, ApiKey.key_prefix, func.count())
            .outerjoin(ApiKey, ApiKey.id == UsageEvent.api_key_id)
            .where(*where)
            .group_by(UsageEvent.api_key_id, ApiKey.name, ApiKey.key_prefix)
            .order_by(func.count().desc())
        ).all()
    ]
    return DeveloperUsage(days=days, per_day=per_day, by_endpoint=by_endpoint, by_key=by_key)

