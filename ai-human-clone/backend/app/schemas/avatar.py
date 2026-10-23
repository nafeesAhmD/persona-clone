import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AvatarType = Literal["uploaded", "generated", "preset"]
AvatarStatus = Literal["pending", "processing", "ready", "failed"]
JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class AvatarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clone_id: uuid.UUID
    avatar_type: AvatarType
    status: AvatarStatus
    is_active: bool
    width: int
    height: int
    mouth_x: float
    mouth_y: float
    mouth_width: float
    face_detected: bool
    error_message: str | None
    # Served to the owner only (login required).
    image_url: str
    created_at: datetime
    updated_at: datetime


class AvatarPreset(BaseModel):
    id: str
    name: str


class AvatarSettingsRead(BaseModel):
    avatar_enabled: bool
    avatar_consent_given: bool
    avatar_consent_at: datetime | None
    active_avatar: AvatarRead | None
    avatars: list[AvatarRead]
    presets: list[AvatarPreset]
    # None when avatar videos are turned off on this server.
    lipsync_provider: str | None
    voice_enabled: bool
    max_video_seconds: float


class AvatarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avatar_enabled: bool | None = None
    avatar_consent_given: bool | None = None
    active_avatar_id: uuid.UUID | None = None
    # Correct where the mouth is on the active avatar (fractions of the image).
    mouth_x: float | None = Field(default=None, ge=0.05, le=0.95)
    mouth_y: float | None = Field(default=None, ge=0.05, le=0.95)
    mouth_width: float | None = Field(default=None, ge=0.03, le=0.6)


class AvatarStyleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skin: str = "#b98a68"
    hair: str = "#1f1a17"
    hair_style: Literal["short", "long", "bun", "none"] = "short"
    background: str = "#3b4a8f"
    shirt: str = "#2d6a8a"

    @field_validator("skin", "hair", "background", "shirt")
    @classmethod
    def check_color(cls, value: str) -> str:
        if not _COLOR.fullmatch(value):
            raise ValueError("must be a colour like #aabbcc")
        return value.lower()


class AvatarGenerateRequest(BaseModel):
    """Either a built-in preset, or an illustrated avatar in your own colours."""

    model_config = ConfigDict(extra="forbid")

    preset: str | None = Field(default=None, max_length=40)
    style: AvatarStyleRequest | None = None

    @model_validator(mode="after")
    def one_of(self) -> "AvatarGenerateRequest":
        if (self.preset is None) == (self.style is None):
            raise ValueError("give either preset or style")
        return self


class AvatarVideoRequest(BaseModel):
    """Video for one of the clone's answers; its speech is reused from voice replies."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID
    message_id: uuid.UUID


class AvatarTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="Hello, I am an AI Clone.", max_length=500)

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be empty")
        return value


class AvatarJobCreated(BaseModel):
    job_id: uuid.UUID
    status: JobStatus


class AvatarJobRead(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    progress: int
    # Set when completed and the file hasn't expired (VIDEO_RETENTION_HOURS).
    video_url: str | None
    expired: bool = False
    error_message: str | None
    duration_seconds: float | None
    conversation_id: uuid.UUID | None
    message_id: uuid.UUID | None
    provider: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


# --- Live video call (Simli) ------------------------------------------------------


class LiveAvatarStatus(BaseModel):
    """The owner's view of the live face. The face id itself isn't needed by the page."""

    available: bool  # SIMLI_API_KEY is set on the server
    face_status: Literal["none", "processing", "ready", "failed"]
    face_ready: bool
    face_error: str | None
    max_minutes: int


class LiveFaceIdUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    face_id: str = Field(min_length=4, max_length=100)


class LiveCallAvailability(BaseModel):
    can_call: bool
    reason: str | None = None


class LiveCallStart(BaseModel):
    """What the browser needs to join the call: a short-lived token, never the API key."""

    session_token: str
    ice_servers: list[dict]
    max_seconds: int
    max_idle_seconds: int


class LiveCallEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(ge=0, le=24 * 3600)
