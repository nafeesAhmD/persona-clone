import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings

SourceType = Literal["file", "manual_text"]
DocumentStatus = Literal["pending", "processing", "ready", "failed"]
IndexingStatus = Literal["not_indexed", "indexing", "indexed", "indexing_failed"]
MANUAL_MIN_CHARACTERS = 20


class DocumentResponse(BaseModel):
    """Document metadata, used in lists and after uploads.

    Deliberately excludes the stored filename/path and the (possibly large) text.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    original_filename: str | None
    file_type: str | None
    mime_type: str | None
    file_size: int | None
    character_count: int
    error_message: str | None
    # AI memory (vector index), separate from text extraction (`status`).
    indexing_status: IndexingStatus
    indexed_at: datetime | None
    indexing_error: str | None
    chunk_count: int
    # "public": visitors of the public clone may get answers from it.
    visibility: Literal["private", "public"] = "private"
    created_at: datetime
    updated_at: datetime


# The list uses the same shape; the alias keeps the API vocabulary explicit.
DocumentListItem = DocumentResponse


class DocumentDetailResponse(DocumentResponse):
    """Metadata plus the extracted text. Clients must render it as plain text."""

    extracted_text: str | None


class ManualKnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    content: str

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("content")
    @classmethod
    def check_content(cls, value: str) -> str:
        value = value.strip()
        maximum = get_settings().manual_knowledge_max_characters
        if len(value) < MANUAL_MIN_CHARACTERS:
            raise ValueError(f"must be at least {MANUAL_MIN_CHARACTERS} characters")
        if len(value) > maximum:
            raise ValueError(f"must be at most {maximum:,} characters")
        return value


class IndexResult(BaseModel):
    document_id: uuid.UUID
    status: IndexingStatus
    chunk_count: int
    error: str | None = None


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = 5

    @field_validator("top_k")
    @classmethod
    def check_top_k(cls, value: int) -> int:
        maximum = get_settings().max_search_top_k
        if not 1 <= value <= maximum:
            raise ValueError(f"must be between 1 and {maximum}")
        return value

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value


class KnowledgeSearchResult(BaseModel):
    score: float
    document_id: str
    title: str
    source_type: str
    chunk_index: int
    text: str


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchResult]
    message: str | None = None
