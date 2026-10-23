"""The provider interface: what a real-time voice backend must do.

A provider runs one conversation turn (speech or text in; transcript, streamed answer
text and spoken audio out) through `emit`. The WebSocket, sessions, limits and
interruption (cancelling the turn's task) are handled outside, so a provider only
deals with its own services. Only "pipeline" is implemented; an adapter for a hosted
WebRTC service would plug in here.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.models import CloneProfile

# emit(message, binary payload sent right after it or None)
Emit = Callable[[dict, bytes | None], Awaitable[None]]


@dataclass
class TurnContext:
    """Everything a turn needs; ids only (database rows are loaded per turn)."""

    session_id: uuid.UUID
    clone_id: uuid.UUID
    user_id: uuid.UUID | None  # None for a public visitor
    is_public: bool
    speech_mode: str
    conversation_id: uuid.UUID | None = None
    public_token: str | None = None  # the visitor's public chat token (memory only)
    visitor_address: str = "unknown"


class RealtimeProvider(ABC):
    name: str

    @abstractmethod
    def configured(self) -> bool:
        """True when every service the provider needs is set up."""

    @abstractmethod
    def capabilities(self, clone: CloneProfile) -> dict:
        """RealtimeCapabilities fields for this clone (honest: only what really works)."""

    @abstractmethod
    async def run_turn(
        self, ctx: TurnContext, turn: int, *, audio: bytes | None, text: str | None, emit: Emit
    ) -> None:
        """One turn. Must be cancellable at any await (interruption cancels the task)."""
