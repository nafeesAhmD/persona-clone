import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings
from app.schemas.clone import Visibility

ContentVisibility = Literal["private", "public"]
SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,48})[a-z0-9]$")
# Paths the site uses itself; a clone can't take them.
RESERVED_SLUGS = {"explore", "api", "admin", "new", "login", "register", "dashboard", "settings", "c", "clone", "clones"}


class SlugUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str

    @field_validator("slug")
    @classmethod
    def check_slug(cls, value: str) -> str:
        if not SLUG_PATTERN.fullmatch(value) or "--" in value:
            raise ValueError(
                "use 3-50 lowercase letters, numbers and single hyphens, starting and ending with a letter or number"
            )
        if value in RESERVED_SLUGS:
            raise ValueError("this name is reserved")
        return value


class VisibilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: ContentVisibility


class PublicSettingsRead(BaseModel):
    slug: str
    visibility: Visibility
    public_chat_enabled: bool
    public_voice_enabled: bool
    public_avatar_enabled: bool
    # Whether the owner's own voice / avatar are set up (public versions need them).
    voice_available: bool
    avatar_available: bool
    public_document_count: int
    public_memory_count: int
    share_path: str
    share_url: str


class PublicSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility | None = None
    public_chat_enabled: bool | None = None
    public_voice_enabled: bool | None = None
    public_avatar_enabled: bool | None = None


class PublicClone(BaseModel):
    """What anyone may see about a public or unlisted clone: no owner account data."""

    id: uuid.UUID
    name: str
    slug: str
    tagline: str | None
    bio: str | None
    profession: str | None
    skills: list[str]
    preferred_language: str | None
    avatar_url: str | None
    visibility: Visibility
    public_chat_enabled: bool
    voice_enabled: bool
    avatar_enabled: bool
    # Phase 17: the live voice conversation is offered to visitors.
    realtime_voice_available: bool = False


class PublicCloneCard(BaseModel):
    name: str
    slug: str
    tagline: str | None
    profession: str | None
    skills: list[str]
    preferred_language: str | None
    avatar_url: str | None


class PublicCloneList(BaseModel):
    items: list[PublicCloneCard]
    page: int
    limit: int
    total: int


class PublicChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    # The visitor's session token (also accepted in the X-Public-Session header).
    session_id: str | None = Field(default=None, max_length=200, validation_alias=AliasChoices("session_id", "session_token"))
    input_mode: Literal["text", "voice"] = "text"
    # Only checked when PUBLIC_CAPTCHA_ENABLED=true, when a new session starts.
    captcha_token: str | None = Field(default=None, max_length=4000)

    @field_validator("message")
    @classmethod
    def check_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        maximum = get_settings().max_public_message_length
        if len(value) > maximum:
            raise ValueError(f"must be at most {maximum:,} characters")
        return value


class PublicMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    input_mode: Literal["text", "voice"] = "text"
    created_at: datetime


class PublicSource(BaseModel):
    title: str


class PublicChatResponse(BaseModel):
    session_id: str
    expires_at: datetime
    message: PublicMessage
    sources: list[PublicSource]
    messages_left: int


class PublicSessionRead(BaseModel):
    expires_at: datetime
    messages: list[PublicMessage]
    messages_left: int


class PublicMediaResponse(BaseModel):
    audio_url: str


class PublicJobCreated(BaseModel):
    job_id: uuid.UUID
    status: str


class PublicJobRead(BaseModel):
    job_id: uuid.UUID
    status: str
    progress: int
    video_url: str | None
    error_message: str | None
