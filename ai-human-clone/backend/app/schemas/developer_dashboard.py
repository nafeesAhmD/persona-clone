"""Response schemas for the developer dashboard (/api/developer/overview, /usage) and the
admin developer view (/api/admin/developer/*). Counts and labels only: never a key,
key hash or webhook secret."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeveloperOverview(BaseModel):
    plan: str
    api_requests_30d: int
    chat_requests_30d: int
    successful_requests_30d: int
    failed_requests_30d: int
    monthly_requests: int
    # 0 means no monthly limit.
    monthly_limit: int
    rate_limit_per_minute: int
    active_keys: int
    active_webhooks: int


class UsagePerDay(BaseModel):
    day: str
    requests: int
    errors: int


class UsageByEndpoint(BaseModel):
    endpoint: str
    requests: int
    errors: int
    avg_duration_ms: float | None


class UsageByKey(BaseModel):
    key_id: uuid.UUID
    name: str
    key_prefix: str
    requests: int


class DeveloperUsage(BaseModel):
    days: int
    per_day: list[UsagePerDay]
    by_endpoint: list[UsageByEndpoint]
    by_key: list[UsageByKey]


# --- Admin --------------------------------------------------------------------------


class AdminEndpointRow(BaseModel):
    endpoint: str
    requests: int
    errors: int


class AdminOrgUsageRow(BaseModel):
    organization_id: uuid.UUID
    name: str
    requests: int


class AdminPlanUsageRow(BaseModel):
    plan: str
    requests: int


class AdminDeveloperOverview(BaseModel):
    api_requests_24h: int
    api_requests_30d: int
    active_keys: int
    revoked_keys: int
    expired_keys: int
    active_webhooks: int
    webhook_failures_24h: int
    rate_limit_events_24h: int
    api_errors_24h: int
    top_endpoints: list[AdminEndpointRow]
    usage_by_organization: list[AdminOrgUsageRow]
    usage_by_plan: list[AdminPlanUsageRow]


class AdminApiKeyRow(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    owner_type: Literal["user", "organization"]
    owner: str | None
    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    status: Literal["active", "revoked", "expired"]
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class AdminKeyRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=300)
