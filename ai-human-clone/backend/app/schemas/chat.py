import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.config import get_settings


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    conversation_id: uuid.UUID | None = None
    # "voice" when the message is a transcript of the user's speech (a display marker only).
    input_mode: Literal["text", "voice"] = "text"

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


class ChatSource(BaseModel):
    """A knowledge source used for an answer: which document, not its text."""

    document_id: str
    title: str
    score: float


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    input_mode: Literal["text", "voice"] = "text"
    created_at: datetime
    # The newest talking-avatar video of this answer, if one was made (owner's chat).
    avatar_job_id: uuid.UUID | None = None
    avatar_job_status: str | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: MessageRead
    sources: list[ChatSource]
    # Approved long-term memories included in the answer's context (a count, not their text).
    memories_used: int = 0


class ConversationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clone_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationListItem):
    messages: list[MessageRead]
