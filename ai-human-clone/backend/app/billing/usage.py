import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.billing.exceptions import UsageLimitError
from app.models import AnalyticsEvent, Conversation, Document, Message, Subscription, Plan, UsageEvent


def _month_start(dt: datetime | None = None) -> datetime:
    d = dt or datetime.now(timezone.utc)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_end(dt: datetime | None = None) -> datetime:
    start = _month_start(dt)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return end - timedelta(microseconds=1)


def get_user_subscription(db: Session, user_id: str | uuid.UUID) -> Subscription | None:
    # Callers pass the id as text or UUID; the column needs a UUID.
    user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    return db.query(Subscription).filter(Subscription.user_id == user_id).order_by(Subscription.created_at.desc()).first()


def get_plan(db: Session, plan_id: str | uuid.UUID) -> Plan | None:
    # Like get_user_subscription: the key must be a UUID (text ids fail on some databases).
    return db.get(Plan, plan_id if isinstance(plan_id, uuid.UUID) else uuid.UUID(str(plan_id)))


def get_default_free_plan(db: Session) -> Plan | None:
    return db.query(Plan).filter(Plan.slug == "free").first()


def ensure_free_plan(db: Session, user_id: str):
    existing = get_user_subscription(db, user_id)
    if existing:
        return existing
    plan = get_default_free_plan(db)
    if not plan:
        return None
    sub = Subscription(
        user_id=user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)),
        plan_id=plan.id,
        status="active",
        billing_cycle=plan.billing_interval or "month",
        current_period_start=_month_start(),
        current_period_end=_month_end(),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub
