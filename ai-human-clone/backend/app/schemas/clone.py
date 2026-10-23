import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResponseLength = Literal["short", "medium", "detailed"]
Visibility = Literal["private", "public", "unlisted"]
CloneStatus = Literal["draft", "active", "disabled"]

MAX_SKILLS = 30
MAX_SKILL_LENGTH = 50


def _clean_text(value: str | None) -> str | None:
    """Trim; empty strings become None so optional fields can be cleared."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_skills(skills: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        skill = " ".join(skill.split())
        if not skill:
            continue
        if len(skill) > MAX_SKILL_LENGTH:
            raise ValueError(f"each skill must be at most {MAX_SKILL_LENGTH} characters")
        if skill.lower() not in seen:  # drop case-insensitive duplicates, keep first spelling
            seen.add(skill.lower())
            cleaned.append(skill)
    if len(cleaned) > MAX_SKILLS:
        raise ValueError(f"at most {MAX_SKILLS} skills")
    return cleaned


def _check_avatar_url(value: str | None) -> str | None:
    value = _clean_text(value)
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("must be an http(s) URL")
    return value


class _CloneFields(BaseModel):
    """Editable settings shared by create and update."""

    tagline: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=5000)
    profession: str | None = Field(default=None, max_length=120)
    skills: list[str] = Field(default_factory=list, max_length=100)
    preferred_language: str | None = Field(default=None, max_length=60)
    communication_style: str | None = Field(default=None, max_length=100)
    personality_description: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=500)

    @field_validator(
        "tagline", "bio", "profession", "preferred_language", "communication_style", "personality_description"
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, value: list[str]) -> list[str]:
        return _clean_skills(value)

    @field_validator("avatar_url")
    @classmethod
    def check_avatar_url(cls, value: str | None) -> str | None:
        return _check_avatar_url(value)


class CloneCreate(_CloneFields):
    # owner_id, slug, id and timestamps are set by the server and rejected if sent.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    response_length: ResponseLength = "medium"
    visibility: Visibility = "private"
    status: CloneStatus = "active"
    owner_consent: bool

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("owner_consent")
    @classmethod
    def consent_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("you can only create a clone of yourself, with your consent")
        return value


class CloneUpdate(_CloneFields):
    """Partial update: only fields present in the request change. owner_id/slug can't be set."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    skills: list[str] | None = Field(default=None, max_length=100)
    response_length: ResponseLength | None = None
    visibility: Visibility | None = None
    status: CloneStatus | None = None

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_skills(value)


class CloneSummary(BaseModel):
    """One card in "my clones" / the public list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    tagline: str | None
    profession: str | None
    skills: list[str]
    preferred_language: str | None
    visibility: Visibility
    status: CloneStatus
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
    # Knowledge sources (documents + manual entries), how many are in AI memory,
    # and how many memory chunks those produced.
    knowledge_count: int = 0
    indexed_count: int = 0
    chunk_count: int = 0
    # Public access switches (the owner's dashboard shows them).
    public_chat_enabled: bool = False
    public_voice_enabled: bool = False
    public_avatar_enabled: bool = False


class CloneResponse(CloneSummary):
    """Full settings, returned to the owner only."""

    bio: str | None
    communication_style: str | None
    personality_description: str | None
    response_length: ResponseLength


class CloneChatProfile(BaseModel):
    """What the chat screen shows: no private settings, plus whether the viewer owns it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    tagline: str | None
    profession: str | None
    preferred_language: str | None
    avatar_url: str | None
    status: CloneStatus
    is_owner: bool = False
    # Whether any knowledge is in AI memory (the chat shows a hint when not).
    has_knowledge: bool = False
    # Whether voice chat is on (the chat shows the microphone only then).
    voice_enabled: bool = False
    # Whether talking-avatar replies are on (owner's chat only).
    avatar_enabled: bool = False
