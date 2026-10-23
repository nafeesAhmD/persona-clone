"""Admin API schemas.

Every response model lists its fields explicitly, so nothing sensitive (password
hashes, session tokens, prompts, document text, private messages, API keys) can
slip out by being added to a database model later. Request models forbid extra
fields, so `is_admin` or similar can never be mass-assigned.
"""

import uuid
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    limit: int
    total: int


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Dashboard ----------------------------------------------------------------------


class HealthItem(BaseModel):
    name: str
    status: Literal["healthy", "degraded", "unavailable", "not_configured", "disabled"]
    detail: str | None = None  # a safe description (provider name, model), never a secret


class DashboardStats(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    admin_users: int
    total_clones: int
    public_clones: int
    unlisted_clones: int
    private_clones: int
    disabled_clones: int
    total_documents: int
    total_memories: int
    total_conversations: int
    total_messages: int
    public_sessions: int
    security_events_24h: int
    errors_24h: int
    usage_events_24h: int
    maintenance_mode: bool
    health: list[HealthItem]


# --- Users --------------------------------------------------------------------------


class AdminUserRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    username: str
    full_name: str | None
    is_active: bool
    is_admin: bool
    created_at: datetime
    clone_count: int = 0


class AdminUserDetail(AdminUserRow):
    updated_at: datetime
    locked_until: datetime | None
    document_count: int
    conversation_count: int
    message_count: int
    memory_count: int


class UserStatusUpdate(_Strict):
    is_active: bool
    reason: str | None = Field(default=None, max_length=300)


# --- Clones -------------------------------------------------------------------------


class AdminCloneRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    owner_email: str
    visibility: str
    status: str
    admin_disabled: bool
    public_chat_enabled: bool
    created_at: datetime


class AdminCloneDetail(AdminCloneRow):
    tagline: str | None
    profession: str | None
    public_voice_enabled: bool
    public_avatar_enabled: bool
    voice_enabled: bool
    avatar_enabled: bool
    updated_at: datetime
    document_count: int
    public_document_count: int
    memory_count: int
    public_memory_count: int
    conversation_count: int
    message_count: int
    public_session_count: int


class CloneStatusUpdate(_Strict):
    status: Literal["active", "disabled"]
    reason: str | None = Field(default=None, max_length=300)


# --- Content moderation ---------------------------------------------------------------


class PublicCloneItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_email: str
    visibility: str
    status: str
    tagline: str | None
    profession: str | None
    public_chat_enabled: bool
    created_at: datetime


class PublicDocumentItem(BaseModel):
    id: uuid.UUID
    title: str
    clone_id: uuid.UUID
    clone_name: str
    owner_email: str
    source_type: str
    character_count: int
    created_at: datetime


class PublicMemoryItem(BaseModel):
    """Public memories are shown to visitors' clones, so moderators may read them."""

    id: uuid.UUID
    clone_id: uuid.UUID
    clone_name: str
    owner_email: str
    memory_type: str
    content: str
    created_at: datetime


class ModerationAction(_Strict):
    reason: str | None = Field(default=None, max_length=300)


# --- Logs ---------------------------------------------------------------------------


class SecurityEventRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    severity: str
    user_id: uuid.UUID | None
    ip_address: str | None
    user_agent: str | None
    details: dict
    created_at: datetime


class AuditLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admin_user_id: uuid.UUID
    admin_email: str | None = None
    action: str
    target_type: str
    target_id: str | None
    details: dict
    created_at: datetime


class ErrorEventRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    error_type: str
    category: str
    method: str | None
    endpoint: str | None
    status_code: int
    user_id: uuid.UUID | None
    clone_id: uuid.UUID | None
    message: str | None
    location: str | None
    created_at: datetime


# --- Usage --------------------------------------------------------------------------


class UsageRow(BaseModel):
    event_type: str
    provider: str | None
    requests: int
    failed: int
    input_units: float
    output_units: float
    avg_duration_ms: float | None
    estimated_cost: float | None = None


class UsageDay(BaseModel):
    day: str
    requests: int


class TopEntry(BaseModel):
    id: uuid.UUID
    label: str
    requests: int


class UsageReport(BaseModel):
    days: int
    total_requests: int
    rows: list[UsageRow]
    per_day: list[UsageDay]
    top_users: list[TopEntry]
    top_clones: list[TopEntry]
    cost_configured: bool
    estimated_total_cost: float | None
    note: str


# --- System and settings --------------------------------------------------------------


class SystemHealth(BaseModel):
    status: Literal["healthy", "degraded"]
    version: str
    environment: str
    services: list[HealthItem]


class PlatformSettingsRead(BaseModel):
    maintenance_mode: bool
    public_registration_enabled: bool
    public_clone_discovery_enabled: bool
    public_chat_enabled: bool
    rate_limits: dict[str, int]
    default_rate_limits: dict[str, int]
    updated_at: datetime | None
    updated_by: uuid.UUID | None


RateLimitName = Literal["login", "chat", "public_chat", "public_voice", "public_avatar", "voice", "avatar_video"]


class PlatformSettingsUpdate(_Strict):
    maintenance_mode: bool | None = None
    public_registration_enabled: bool | None = None
    public_clone_discovery_enabled: bool | None = None
    public_chat_enabled: bool | None = None
    # Per-minute overrides; null removes an override (back to the configured default).
    rate_limits: dict[RateLimitName, int | None] | None = None

    def limits_valid(self) -> bool:
        return all(v is None or 1 <= v <= 1000 for v in (self.rate_limits or {}).values())


class PlatformStatus(BaseModel):
    """Public: what the frontend needs for banners. No internals."""

    maintenance_mode: bool
    public_registration_enabled: bool
    public_clone_discovery_enabled: bool
    public_chat_enabled: bool
    message: str | None = None
