import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.billing import usage
from app.billing.exceptions import UsageLimitError
from app.billing.plans import DEFAULT_PLANS
from app.models import Plan, Subscription, UsageEvent


def get_plans(db: Session) -> list[Plan]:
    return db.query(Plan).filter(Plan.is_active == True).all()


def seed_plans(db: Session):
    for plan_data in DEFAULT_PLANS:
        existing = db.query(Plan).filter(Plan.slug == plan_data["slug"]).first()
        if existing:
            continue
        db.add(Plan(**plan_data))
    db.commit()


def get_subscription(db: Session, user_id: str) -> Subscription | None:
    sub = usage.get_user_subscription(db, user_id)
    if not sub:
        sub = usage.ensure_free_plan(db, user_id)
    return sub


def set_subscription_status(db: Session, sub: Subscription, status: str) -> Subscription:
    """Change a subscription's status and send the subscription.updated webhook event.

    Use this for every status change (cancel, provider webhooks, renewals) so
    developers' webhooks hear about it."""
    previous = sub.status
    if previous == status:
        return sub
    sub.status = status
    if status == "cancelled" and sub.cancelled_at is None:
        sub.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    try:
        from app.developer.webhooks import emit

        emit(
            "subscription.updated",
            {"subscription_id": sub.id, "plan_id": sub.plan_id, "status": status, "previous_status": previous},
            user_id=sub.user_id,
        )
    except Exception:  # noqa: BLE001 - webhooks must never break billing
        pass
    return sub


def check_limit(
    db: Session,
    user_id: str,
    limit_key: str,
    amount: int = 1,
    raise_on_exceed: bool = True,
) -> tuple[bool, int, int, datetime | None]:
    sub = get_subscription(db, user_id)
    if not sub:
        return True, 0, 0, None
    plan = usage.get_plan(db, str(sub.plan_id))
    if not plan:
        return True, 0, 0, None
    limits = plan.limits or {}
    limit = limits.get(limit_key, 0)
    if limit <= 0:
        return True, 0, 0, sub.current_period_end

    used = 0
    if limit_key == "chat_messages":
        from app.models import Conversation, Message

        used = (
            db.query(Message)
            .join(Conversation)
            .filter(Conversation.user_id == user_id)
            .count()
        )
    elif limit_key == "realtime_voice_sessions":
        # Phase 17: real-time voice sessions started this month.
        from app.models import RealtimeVoiceSession

        used = (
            db.query(RealtimeVoiceSession)
            .filter(RealtimeVoiceSession.owner_id == (user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))))
            .filter(RealtimeVoiceSession.created_at >= usage._month_start())
            .count()
        )
    elif limit_key == "clones":
        from app.models import CloneProfile

        used = db.query(CloneProfile).filter(CloneProfile.owner_id == user_id).count()
    elif limit_key == "documents":
        from app.models import CloneProfile, Document

        used = db.query(Document).join(CloneProfile).filter(CloneProfile.owner_id == user_id).count()
    else:
        used = db.query(UsageEvent).filter(UsageEvent.user_id == user_id).filter(UsageEvent.event_type == limit_key).count()

    remaining = limit - used
    if remaining < amount and raise_on_exceed:
        raise UsageLimitError(
            {
                "message": f"You have reached your {limit_key} limit.",
                "limit": limit,
                "used": used,
                "reset_at": sub.current_period_end,
            }
        )
    return remaining >= amount, used, limit, sub.current_period_end
