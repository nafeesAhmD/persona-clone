"""Marketplace request/response models (docs/phase18/contract.md).

Public models carry public profile metadata only: never owner account data, private
fields, moderation notes, documents, memories or conversations."""

import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.marketplace.categories import SLUGS
from app.models.marketplace import REPORT_REASONS, REPORT_STATUSES

TAG_PATTERN = re.compile(r"^[a-z0-9 +#.-]{2,30}$")
MAX_TAGS = 8
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

Sort = Literal["relevance", "newest", "popular"]
ReportReason = Literal[REPORT_REASONS]  # type: ignore[valid-type]
ReportStatus = Literal[REPORT_STATUSES]  # type: ignore[valid-type]


def normalize_tag(value: str) -> str:
    tag = " ".join(value.strip().lower().split())
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("tags use 2-30 letters, numbers, spaces or + # . -")
    return tag


def plain_text(value: str | None) -> str | None:
    """Trimmed text without control characters; empty becomes None. Rendered as text."""
    if value is None:
        return None
    value = _CONTROL.sub("", value).strip()
    return value or None


# --- Public ----------------------------------------------------------------------------


class CategoryRef(BaseModel):
    slug: str
    name: str


class Capabilities(BaseModel):
    chat: bool
    voice: bool
    avatar: bool
    realtime_voice: bool


class MarketplaceCard(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    profession: str | None
    short_description: str | None
    tagline: str | None
    avatar_url: str | None
    category: CategoryRef | None
    tags: list[str]
    skills: list[str]
    capabilities: Capabilities
    published_at: datetime | None
    featured: bool


class MarketplaceProfile(MarketplaceCard):
    bio: str | None
    preferred_language: str | None
    favorites: int
    is_favorite: bool
    public_url: str


class MarketplacePage(BaseModel):
    items: list[MarketplaceCard]
    total: int
    page: int
    page_size: int
    sort: str


class CategoryCount(BaseModel):
    slug: str
    name: str
    description: str
    count: int


class TagCount(BaseModel):
    tag: str
    count: int


# --- Favorites and reports -------------------------------------------------------------


class FavoriteRead(BaseModel):
    clone_id: uuid.UUID
    created_at: datetime


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("description")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return plain_text(value)


class ReportCreated(BaseModel):
    id: uuid.UUID
    status: str


# --- Owner ---------------------------------------------------------------------------


class Requirement(BaseModel):
    key: str
    ok: bool
    label: str


class OwnerMarketplace(BaseModel):
    enabled: bool
    category: str | None
    tags: list[str]
    short_description: str | None
    published_at: datetime | None
    suspended: bool
    eligible: bool
    listed: bool
    requirements: list[Requirement]
    preview: MarketplaceCard
    public_url: str


class OwnerMarketplaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    category: str | None = None
    tags: list[str] | None = None
    short_description: str | None = Field(default=None, max_length=200)
    confirm_publish: bool = False

    @field_validator("category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        if value is not None and value not in SLUGS:
            raise ValueError(f"category must be one of: {', '.join(SLUGS)}")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        tags = list(dict.fromkeys(normalize_tag(tag) for tag in value))
        if len(tags) > MAX_TAGS:
            raise ValueError(f"at most {MAX_TAGS} tags")
        return tags

    @field_validator("short_description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return plain_text(value)


class DailyCount(BaseModel):
    date: date
    views: int
    favorites: int


class OwnerAnalytics(BaseModel):
    days: int
    views: int
    favorites: int
    public_chat_starts: int
    daily: list[DailyCount]


# --- Admin -----------------------------------------------------------------------------


class AdminReportClone(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class AdminReport(BaseModel):
    id: uuid.UUID
    clone: AdminReportClone
    reporter: str  # the reporter's email, or "anonymous"
    reason: str
    description: str | None
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    resolution_note: str | None


class AdminReportPage(BaseModel):
    items: list[AdminReport]
    total: int
    page: int
    page_size: int


class AdminReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReportStatus
    resolution_note: str | None = Field(default=None, max_length=500)

    @field_validator("resolution_note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return plain_text(value)


class AdminCloneMarketplaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suspended: bool | None = None
    reason: str | None = Field(default=None, max_length=200)
    # Sent as null: no longer featured. Not sent: unchanged (see model_fields_set).
    featured_rank: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        return plain_text(value)


class AdminCloneMarketplace(BaseModel):
    clone_id: uuid.UUID
    slug: str
    marketplace_enabled: bool
    suspended: bool
    suspended_reason: str | None
    featured_rank: int | None


AdminCloneFilter = Literal["listed", "suspended", "featured", "all"]


class AdminMarketplaceClone(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    marketplace_enabled: bool
    listed: bool
    suspended: bool
    suspended_reason: str | None
    featured_rank: int | None
    published_at: datetime | None
    open_reports: int


class AdminMarketplaceClonePage(BaseModel):
    items: list[AdminMarketplaceClone]
    total: int
    page: int
    page_size: int
