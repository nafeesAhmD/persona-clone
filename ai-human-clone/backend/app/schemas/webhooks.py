"""Schemas for webhook management. The signing secret appears only in WebhookCreated."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WebhookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    events: list[str] = Field(min_length=1, max_length=20)
    # Set to create an organization webhook (owner/admin only); omit for a personal one.
    organization_id: uuid.UUID | None = None
    is_active: bool = True


class WebhookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, min_length=1, max_length=2000)
    events: list[str] | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None


class WebhookRead(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    owner_type: Literal["user", "organization"]
    organization_id: uuid.UUID | None
    failure_count: int
    last_delivery_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebhookCreated(WebhookRead):
    secret: str = Field(description="The signing secret (whsec_...). Shown only once: store it now.")


class WebhookEventInfo(BaseModel):
    event: str
    description: str


class WebhookTestResult(BaseModel):
    delivery_id: uuid.UUID
    status: Literal["pending", "delivering", "delivered", "failed"]


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: str
    event_type: str
    status: Literal["pending", "delivering", "delivered", "failed"]
    response_status: int | None
    attempts: int
    last_error: str | None
    delivered_at: datetime | None
    next_retry_at: datetime | None
    created_at: datetime


class DeliveryPage(BaseModel):
    items: list[DeliveryRead]
    page: int
    limit: int
    total: int
