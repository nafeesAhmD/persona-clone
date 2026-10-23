import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _as_text(value: Any) -> Any:
    """Database ids are UUIDs; the API sends them as strings."""
    return str(value) if isinstance(value, uuid.UUID) else value


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str

    _id_text = field_validator("id", mode="before")(_as_text)
    name: str
    slug: str
    description: str | None = None
    price: float = 0.0
    currency: str = "USD"
    billing_interval: str = "month"
    is_active: bool = True
    is_public: bool = True
    limits: dict[str, Any] = {}
    features: dict[str, Any] = {}


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    plan_id: str
    provider: str | None = None
    status: str
    billing_cycle: str
    started_at: datetime
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancelled_at: datetime | None = None

    _ids_text = field_validator("id", "user_id", "plan_id", mode="before")(_as_text)


class UsageItem(BaseModel):
    """One plan limit: how much is used now against the plan's allowance."""

    key: str
    label: str
    used: float = 0
    # None means unlimited (the plan has no limit for it, or a limit of 0).
    limit: float | None = None
    # "month": counted since the start of the month and reset on reset_at; "total": a running total.
    period: Literal["month", "total"] = "month"
    unit: str | None = None


class UsageSummary(BaseModel):
    plan_slug: str = "free"
    plan_name: str = "Free"
    billing_enabled: bool = False
    period_start: datetime | None = None
    items: list[UsageItem] = []
    # The totals below are kept for older clients.
    chat_messages: int = 0
    clones_created: int = 0
    knowledge_storage_mb: float = 0.0
    voice_requests: int = 0
    tts_requests: int = 0
    avatar_requests: int = 0
    public_chat_requests: int = 0
    reset_at: datetime | None = None


class UsageLimitErrorResponse(BaseModel):
    error: str = "usage_limit_reached"
    message: str
    limit: int
    used: int
    reset_at: datetime | None = None
