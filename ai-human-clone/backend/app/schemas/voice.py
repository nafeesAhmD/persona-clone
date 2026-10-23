import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.chat import ChatSource, MessageRead

VoiceLanguage = Literal["auto", "en", "ur"]


class VoiceOptionRead(BaseModel):
    id: str
    name: str
    description: str
    is_custom: bool


VoiceCloneState = Literal["none", "processing", "ready", "failed"]


class VoiceCloneStatus(BaseModel):
    """The owner's personal voice clone (ElevenLabs, or the self-hosted Chatterbox service)."""

    available: bool  # the server can clone voices (ElevenLabs key or local service set up)
    status: VoiceCloneState
    error: str | None
    use_cloned_voice: bool
    consent_at: datetime | None
    # The provider of the existing cloned voice, otherwise the one new recordings go to.
    provider: Literal["elevenlabs", "local"] | None
    min_seconds: float
    max_seconds: float
    max_files: int
    model: str


class VoiceCloneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_cloned_voice: bool


class VoiceSettingsRead(BaseModel):
    voice_enabled: bool
    voice_provider: str | None
    # The voice the clone speaks with: a prebuilt voice, or "elevenlabs:<id>" / "local:<id>" when the
    # owner's cloned voice is in use (also listed in `voices` with is_custom true).
    voice_id: str | None
    voice_language: VoiceLanguage
    voice_consent_given: bool
    voice_consent_at: datetime | None
    # "custom" while the owner's cloned voice is in use, otherwise "ai_generated".
    voice_type: Literal["ai_generated", "custom"]
    # What the server can do right now (None = not configured).
    stt_provider: str | None
    tts_provider: str | None
    voices: list[VoiceOptionRead]
    voice_clone: VoiceCloneStatus


class VoiceSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_enabled: bool | None = None
    voice_provider: str | None = Field(default=None, max_length=40)
    voice_id: str | None = Field(default=None, max_length=100)
    voice_language: VoiceLanguage | None = None
    voice_consent_given: bool | None = None


class TranscriptionResponse(BaseModel):
    text: str
    language: str | None
    duration_seconds: float


class VoiceChatResponse(BaseModel):
    conversation_id: uuid.UUID
    transcript: str
    answer: str
    # Where to fetch the spoken answer (login required, only for this user). None if TTS failed.
    audio_url: str | None
    tts_error: str | None = None
    language: str | None
    duration_seconds: float
    message: MessageRead
    sources: list[ChatSource]
    memories_used: int = 0


class VoiceTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="Hello, this is my AI Clone.", max_length=500)

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be empty")
        return value


class VoiceTestResponse(BaseModel):
    audio_url: str
