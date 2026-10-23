"""API shapes for real-time voice (docs/phase17/contract.md)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

SpeechMode = Literal["voice", "browser"]


class RealtimeCapabilities(BaseModel):
    transport: str = "websocket"
    interruption: bool = True
    streaming_text: bool = True
    server_speech: bool
    cloned_voice: bool
    languages: list[str]


class RealtimeLimits(BaseModel):
    max_duration_seconds: int
    session_ttl_seconds: int
    max_utterance_seconds: float
    max_utterance_bytes: int


class RealtimeSettings(BaseModel):
    available: bool
    reason: str | None
    provider: str
    enabled: bool
    public_enabled: bool
    speech_mode: SpeechMode
    capabilities: RealtimeCapabilities
    limits: RealtimeLimits


class RealtimeSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    public_enabled: bool | None = None
    speech_mode: SpeechMode | None = None


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None


class SessionCreated(BaseModel):
    session_id: uuid.UUID
    status: str
    provider: str
    conversation_id: uuid.UUID | None
    ws_path: str
    ticket: str
    ticket_expires_at: datetime
    expires_at: datetime
    max_duration_seconds: int
    speech_mode: SpeechMode
    capabilities: RealtimeCapabilities


class SessionStatus(BaseModel):
    session_id: uuid.UUID
    status: str
    provider: str
    conversation_id: uuid.UUID | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float | None
    error_code: str | None
    expires_at: datetime
