import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.config import get_settings

MemoryType = Literal[
    "fact",
    "preference",
    "communication_preference",
    "skill",
    "experience",
    "project",
    "goal",
    "background",
    "instruction",
    "other",
]
MemoryStatus = Literal["candidate", "approved", "rejected", "archived"]
MemorySource = Literal["conversation", "manual"]


def _clean_content(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be empty")
    maximum = get_settings().memory_max_length
    if len(value) > maximum:
        raise ValueError(f"must be at most {maximum:,} characters")
    return value


class MemoryCreate(BaseModel):
    """A memory the owner writes themselves (stored as approved)."""

    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    content: str

    @field_validator("content")
    @classmethod
    def check_content(cls, value: str) -> str:
        return _clean_content(value)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType | None = None
    content: str | None = None
    status: MemoryStatus | None = None

    @field_validator("content")
    @classmethod
    def check_content(cls, value: str | None) -> str | None:
        return None if value is None else _clean_content(value)


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clone_id: uuid.UUID
    memory_type: MemoryType
    content: str
    confidence: float | None
    status: MemoryStatus
    source: MemorySource
    source_conversation_id: uuid.UUID | None
    # "public": usable for visitors of the public clone once approved.
    visibility: Literal["private", "public"] = "private"
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class ClearMemoriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class ClearMemoriesResponse(BaseModel):
    deleted: int


class ExtractionSkipped(BaseModel):
    """Suggestions the model made that were not kept, by reason."""

    duplicates: int = 0
    sensitive: int = 0
    invalid: int = 0


class ExtractionResponse(BaseModel):
    candidates: list[MemoryRead]
    skipped: ExtractionSkipped
    message: str
