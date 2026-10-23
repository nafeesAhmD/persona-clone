"""Request and response schemas of the public developer API (/api/v1).

Every response model is explicit: only fields that are safe to give to a third-party
app. Never included: system prompts, personality / communication-style text, bios,
private memory content, document text beyond a short search snippet, filesystem
paths, internal URLs that need a browser session, provider ids or API keys.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import get_settings

SNIPPET_CHARS = 500


# --- Clones -------------------------------------------------------------------------


class ApiClone(BaseModel):
    """A clone's public profile fields."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "6f1c1b7e-8d0a-4c1e-9a43-0b6f7f3d2a10",
                "name": "Ayaan AI",
                "slug": "ayaan-ai",
                "tagline": "Ask me about web development",
                "profession": "Software Developer",
                "skills": ["Python", "FastAPI"],
                "preferred_language": "English",
                "visibility": "private",
                "status": "active",
                "voice_enabled": True,
                "avatar_enabled": False,
                "created_at": "2026-10-01T09:30:00Z",
                "updated_at": "2026-10-02T10:00:00Z",
            }
        },
    )

    id: uuid.UUID
    name: str
    slug: str
    tagline: str | None
    profession: str | None
    skills: list[str] = []
    preferred_language: str | None
    visibility: str
    status: str
    voice_enabled: bool
    avatar_enabled: bool
    organization_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("skills", mode="before")
    @classmethod
    def no_null_skills(cls, value):
        return value or []


class ApiCloneList(BaseModel):
    data: list[ApiClone]


# --- Chat ---------------------------------------------------------------------------


class ApiChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"message": "What technologies have you worked with?", "conversation_id": None}},
    )

    message: str = Field(description="The user's message.")
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Continue an existing conversation of this clone; null starts a new one."
    )

    @field_validator("message")
    @classmethod
    def check_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        maximum = get_settings().max_chat_message_length
        if len(value) > maximum:
            raise ValueError(f"must be at most {maximum:,} characters")
        return value


class ApiSource(BaseModel):
    """A knowledge source used for an answer: its title and relevance, never its text."""

    title: str
    score: float


class ApiChatResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "conversation_id": "0a4c2d55-58a5-4c55-9a63-1a2bfa6f0e11",
                "message_id": "5a1f3e0b-2a8e-4bb8-8ab1-6c2f0c7d9e22",
                "message": "I mostly work with Python, FastAPI and React.",
                "sources": [{"title": "Resume", "score": 0.82}],
                "memories_used": 0,
                "created_at": "2026-10-05T12:00:00Z",
            }
        }
    )

    conversation_id: uuid.UUID
    message_id: uuid.UUID
    message: str = Field(description="The clone's answer.")
    sources: list[ApiSource]
    memories_used: int = Field(0, description="How many approved long-term memories informed the answer (a count).")
    created_at: datetime


# --- Conversations ------------------------------------------------------------------


class ApiMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    input_mode: Literal["text", "voice"] = "text"
    created_at: datetime


class ApiConversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clone_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ApiConversationList(BaseModel):
    data: list[ApiConversation]


class ApiConversationDetail(ApiConversation):
    messages: list[ApiMessage]


# --- Search -------------------------------------------------------------------------


class ApiSearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"query": "Which databases do you use?", "top_k": 5}}
    )

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def check_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ApiSearchResult(BaseModel):
    title: str
    source_type: str
    score: float
    snippet: str = Field(description=f"The matching passage, at most {SNIPPET_CHARS} characters.")


class ApiSearchResponse(BaseModel):
    query: str
    scope: Literal["all", "public"] = Field(description="'all' with clone:search, 'public' with clone:knowledge:read.")
    results: list[ApiSearchResult]


# --- Voice --------------------------------------------------------------------------


class ApiTranscription(BaseModel):
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class ApiTtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"text": "Hello, thanks for calling!"}})

    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be empty")
        return value


class ApiAudio(BaseModel):
    audio_url: str = Field(description="Download with the same API key (GET, scope voice:tts). Expires after a while.")


class ApiVoiceChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    transcript: str
    answer: str
    audio_url: str | None = Field(description="The spoken answer (API route); null if speech generation failed.")
    tts_error: str | None = None
    language: str | None = None
    duration_seconds: float | None = None
    sources: list[ApiSource]
    memories_used: int = 0


# --- Avatar -------------------------------------------------------------------------


class ApiAvatarVideoRequest(BaseModel):
    """Either `text` (a short test video), or `conversation_id` + `message_id` (an answer)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"text": "Hello, I am an AI Clone."}},
    )

    text: str | None = Field(default=None, max_length=500)
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def one_of(self) -> "ApiAvatarVideoRequest":
        if self.text is not None:
            self.text = " ".join(self.text.split())
        has_text = bool(self.text)
        has_answer = self.conversation_id is not None and self.message_id is not None
        partial_answer = (self.conversation_id is None) != (self.message_id is None)
        if partial_answer or has_text == has_answer:
            raise ValueError("give either text, or conversation_id and message_id")
        return self


class ApiAvatarJob(BaseModel):
    job_id: uuid.UUID
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    video_url: str | None = Field(description="API download route once completed (scope avatar:generate).")
    expired: bool = False
    error_message: str | None = None
    duration_seconds: float | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    created_at: datetime
    completed_at: datetime | None = None


# --- Analytics ----------------------------------------------------------------------


class ApiAnalyticsOverview(BaseModel):
    """Counts only, never message content."""

    clone_id: uuid.UUID
    range: str
    start: datetime
    end: datetime
    total_conversations: int = 0
    total_messages: int = 0
    total_public_sessions: int = 0
    total_documents: int = 0
    total_memories: int = 0
    total_voice_requests: int = 0
    total_avatar_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float | None = None
    total_usage_events: int = 0


class ApiActivityDay(BaseModel):
    date: date
    conversations: int = 0
    messages: int = 0


class ApiActivity(BaseModel):
    clone_id: uuid.UUID
    range: str
    days: list[ApiActivityDay]
