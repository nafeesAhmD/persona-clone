"""Plan-based limits for the developer API, reusing Phase 12 billing plans.

- With BILLING_ENABLED=false everyone is on free-mode limits.
- A personal key uses its user's plan; an organization key its organization's plan.
- Monthly API requests (plan limit "api_requests") and chat messages ("chat_messages")
  count toward the same plan as the rest of the app (no second billing system).
"""

import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import DEFAULT_PLANS
from app.core.config import get_settings
from app.developer.errors import ApiError
from app.developer.rate_limit import Limits
from app.models import Conversation, Message, Plan, UsageEvent

_CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_DEFAULTS = {plan["slug"]: plan["limits"] for plan in DEFAULT_PLANS}


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def plan_slug(db: Session, *, user_id: uuid.UUID | None, organization_id: uuid.UUID | None) -> str:
    if not get_settings().billing_enabled:
        return "free"
    cache_key = f"org:{organization_id}" if organization_id else f"user:{user_id}"
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
            return hit[1]
    slug = "free"
    if organization_id:
        from app.org.services.features import get_org_plan_name

        slug = get_org_plan_name(db, organization_id) or "free"
    elif user_id:
        from app.billing.usage import get_user_subscription

        subscription = get_user_subscription(db, str(user_id))
        if subscription is not None and subscription.status in ("active", "trialing"):
            plan = db.get(Plan, subscription.plan_id)
            slug = plan.slug if plan else "free"
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), slug)
    return slug


def plan_limits(db: Session, slug: str) -> dict:
    limits = dict(_DEFAULTS.get(slug, _DEFAULTS["free"]))
    plan = db.scalar(select(Plan).where(Plan.slug == slug))
    if plan is not None and plan.limits:
        limits.update(plan.limits)
    return limits


def rate_limits(db: Session, *, user_id, organization_id) -> Limits:
    settings = get_settings()
    per_minute = settings.api_rate_limit_per_minute
    if settings.billing_enabled:
        per_minute = int(plan_limits(db, plan_slug(db, user_id=user_id, organization_id=organization_id)).get(
            "api_rate_limit_per_minute", per_minute
        ))
    return Limits(per_minute, max(settings.api_rate_limit_per_hour, per_minute), settings.api_rate_limit_burst)


def _owner_filter(user_id, organization_id):
    if organization_id:
        return UsageEvent.organization_id == organization_id
    return (UsageEvent.user_id == user_id) & UsageEvent.organization_id.is_(None)


def monthly_api_requests(db: Session, *, user_id, organization_id) -> int:
    return db.scalar(
        select(func.count())
        .select_from(UsageEvent)
        .where(UsageEvent.event_type == "API_REQUEST", UsageEvent.created_at >= month_start())
        .where(_owner_filter(user_id, organization_id))
    ) or 0


def _limit_reached(what: str, used: int, limit: int, *, user_id, organization_id) -> ApiError:
    try:
        from app.developer.webhooks import emit

        emit("usage.limit_reached", {"limit": what, "used": used, "allowed": limit}, user_id=user_id, organization_id=organization_id)
    except Exception:  # noqa: BLE001 - a webhook problem must not change the response
        pass
    return ApiError(429, "usage_limit_reached", f"Monthly {what.replace('_', ' ')} limit reached ({limit}).")


def check_api_requests(db: Session, *, user_id, organization_id) -> tuple[int, int]:
    """(used, limit) this month; raises usage_limit_reached at the limit."""
    slug = plan_slug(db, user_id=user_id, organization_id=organization_id)
    limit = int(plan_limits(db, slug).get("api_requests", 0) or 0)
    used = monthly_api_requests(db, user_id=user_id, organization_id=organization_id)
    if limit > 0 and used >= limit:
        raise _limit_reached("api_requests", used, limit, user_id=user_id, organization_id=organization_id)
    return used, limit


def check_chat_messages(db: Session, *, acting_user_id, user_id, organization_id) -> None:
    """Monthly chat messages of the plan, counting every message the acting user sent."""
    slug = plan_slug(db, user_id=user_id, organization_id=organization_id)
    limit = int(plan_limits(db, slug).get("chat_messages", 0) or 0)
    if limit <= 0:
        return
    used = db.scalar(
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == acting_user_id, Message.role == "user", Message.created_at >= month_start())
    ) or 0
    if used >= limit:
        raise _limit_reached("chat_messages", used, limit, user_id=user_id, organization_id=organization_id)


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()
