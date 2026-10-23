"""Schemas for the developer platform. Keys are shown in full only in ApiKeyCreated."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_at: datetime | None = None
    # Set to create an organization key (owner/admin only); omit for a personal key.
    organization_id: uuid.UUID | None = None


class ApiKeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    scopes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    expires_at: datetime | None = None


class ApiKeyRead(BaseModel):
    """A key as listed later: never the secret, only its recognisable prefix."""

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    owner_type: Literal["user", "organization"]
    organization_id: uuid.UUID | None
    status: Literal["active", "revoked", "expired"]
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    key: str = Field(description="The full API key. Shown only once: store it now.")


class ScopeInfo(BaseModel):
    scope: str
    description: str
