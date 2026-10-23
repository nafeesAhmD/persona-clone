import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.billing import service
from app.billing.plans import DEFAULT_PLANS
from app.billing.schemas import PlanRead, SubscriptionRead, UsageItem, UsageSummary
from app.core.config import get_settings
from app.developer import feature_limits
from app.developer.limits import month_start, monthly_api_requests, plan_limits, plan_slug
from app.models import AgentExecution, CloneProfile, Conversation, Document, Message, Plan, UsageEvent

router = APIRouter(prefix="/billing", tags=["billing"])

# Plan limit key -> (label, period, unit). The order is the order shown in the app.
USAGE_KEYS: dict[str, tuple[str, str, str | None]] = {
    "chat_messages": ("Chat messages", "month", None),
    "clones": ("Clones", "total", None),
    "documents": ("Knowledge documents", "total", None),
    "knowledge_mb": ("Knowledge storage", "total", "MB"),
    "voice_requests": ("Voice transcriptions", "month", None),
    "tts_requests": ("Spoken replies", "month", None),
    "avatar_requests": ("Avatar videos", "month", None),
    "public_chat_requests": ("Public chat messages", "month", None),
    "api_requests": ("API requests", "month", None),
    "agent_executions": ("AI agent runs", "month", None),
}


def _billing_enabled_or_403():
    settings = get_settings()
    if not settings.billing_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Billing is disabled")


def _next_month(start: datetime) -> datetime:
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def _current_usage(db: Session, user_id: uuid.UUID, since: datetime) -> dict[str, float]:
    """What the user has used: monthly counters since `since`, running totals otherwise."""
    owned_clones = select(CloneProfile.id).where(CloneProfile.owner_id == user_id)
    personal_clones = select(CloneProfile.id).where(
        CloneProfile.owner_id == user_id, CloneProfile.organization_id.is_(None)
    )
    storage_bytes = db.scalar(
        select(func.coalesce(func.sum(Document.file_size), 0)).where(Document.clone_id.in_(owned_clones))
    ) or 0
    return {
        # Messages the user sent (any clone), like the developer API's chat_messages limit.
        "chat_messages": _count(db, select(func.count()).select_from(Message)
                                .join(Conversation, Conversation.id == Message.conversation_id)
                                .where(Conversation.user_id == user_id, Message.role == "user",
                                       Message.created_at >= since)),
        "clones": _count(db, select(func.count()).select_from(CloneProfile).where(CloneProfile.owner_id == user_id)),
        "documents": _count(db, select(func.count()).select_from(Document).where(Document.clone_id.in_(owned_clones))),
        "knowledge_mb": round(float(storage_bytes) / (1024 * 1024), 2),
        "voice_requests": feature_limits.used_this_month(db, "STT_REQUEST", user_id),
        "tts_requests": feature_limits.used_this_month(db, "TTS_REQUEST", user_id),
        "avatar_requests": feature_limits.used_this_month(db, "AVATAR_JOB", user_id),
        # Visitors' messages to the user's public clones.
        "public_chat_requests": _count(db, select(func.count()).select_from(UsageEvent).where(
            UsageEvent.event_type == "PUBLIC_CHAT_MESSAGE", UsageEvent.clone_id.in_(owned_clones),
            UsageEvent.created_at >= since)),
        "api_requests": monthly_api_requests(db, user_id=user_id, organization_id=None),
        # Agent runs on the user's own (non-organization) clones, as the agent's plan check counts them.
        "agent_executions": _count(db, select(func.count()).select_from(AgentExecution).where(
            AgentExecution.clone_id.in_(personal_clones), AgentExecution.created_at >= since)),
    }


def _plan_name(db: Session, slug: str) -> str:
    plan = db.scalar(select(Plan).where(Plan.slug == slug))
    if plan is not None:
        return plan.name
    return next((p["name"] for p in DEFAULT_PLANS if p["slug"] == slug), slug.title())


def build_usage(db: Session, user_id: uuid.UUID) -> UsageSummary:
    """Usage against the user's plan (free-mode limits while billing is disabled).

    Counts only: no content, no payment or provider details."""
    slug = plan_slug(db, user_id=user_id, organization_id=None)
    limits = plan_limits(db, slug)
    start = month_start()
    reset_at = _next_month(start)
    used = _current_usage(db, user_id, start)
    items = []
    for key, (label, period, unit) in USAGE_KEYS.items():
        limit = limits.get(key)
        limit = float(limit) if isinstance(limit, (int, float)) and limit > 0 else None
        items.append(UsageItem(key=key, label=label, used=used[key], limit=limit, period=period, unit=unit))
    return UsageSummary(
        plan_slug=slug,
        plan_name=_plan_name(db, slug),
        billing_enabled=get_settings().billing_enabled,
        period_start=start,
        reset_at=reset_at,
        items=items,
        chat_messages=int(used["chat_messages"]),
        clones_created=int(used["clones"]),
        knowledge_storage_mb=float(used["knowledge_mb"]),
        voice_requests=int(used["voice_requests"]),
        tts_requests=int(used["tts_requests"]),
        avatar_requests=int(used["avatar_requests"]),
        public_chat_requests=int(used["public_chat_requests"]),
    )


@router.get("/plans", response_model=list[PlanRead])
def get_plans(db: DbSession):
    plans = service.get_plans(db)
    if not plans:
        # Plans haven't been seeded into this database: show the built-in ones (read only).
        return [PlanRead(id=p["slug"], **p) for p in DEFAULT_PLANS]
    return [PlanRead.model_validate(p) for p in plans]


@router.get("/subscription", response_model=SubscriptionRead)
def get_subscription(user: CurrentUser, db: DbSession):
    sub = service.get_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return SubscriptionRead.model_validate(sub)


@router.get("/usage", response_model=UsageSummary)
def get_usage(user: CurrentUser, db: DbSession):
    return build_usage(db, user.id)


@router.post("/checkout")
def checkout(user: CurrentUser, db: DbSession):
    _billing_enabled_or_403()
    return {"url": None}


@router.post("/cancel")
def cancel(user: CurrentUser, db: DbSession):
    _billing_enabled_or_403()
    sub = service.get_subscription(db, user.id)
    if sub:
        service.set_subscription_status(db, sub, "cancelled")  # also sends subscription.updated
    return {"status": "cancelled"}


@router.post("/portal")
def portal(user: CurrentUser, db: DbSession):
    _billing_enabled_or_403()
    return {"url": None}


@router.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, db: DbSession):
    _billing_enabled_or_403()
    await request.body()
    return {"status": "received", "provider": provider}
