"""Live real-time voice sessions in this process: one-time tickets, the running
WebSocket and its end signal.

Tickets live only here (hashed in the database too, for the record) and are consumed
on first use. With several backend processes this registry must move to a shared
store; the database row stays the source of truth for status and limits.
"""

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.realtime_voice.exceptions import RealtimeVoiceError
from app.realtime_voice.provider_base import TurnContext
from app.realtime_voice.safety import ticket_matches


@dataclass
class LiveSession:
    ctx: TurnContext
    ticket_hash: str
    ticket_expires: float  # time.monotonic()
    max_duration_seconds: int
    ticket_used: bool = False
    connected: bool = False
    end_reason: str | None = None
    loop: asyncio.AbstractEventLoop | None = None
    end_event: asyncio.Event | None = None
    extra: dict = field(default_factory=dict)

    def request_end(self, reason: str) -> None:
        """Ask the WebSocket (running on its own event loop) to finish. Thread-safe."""
        self.end_reason = self.end_reason or reason
        if self.loop is not None and self.end_event is not None:
            self.loop.call_soon_threadsafe(self.end_event.set)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, LiveSession] = {}
        self._lock = threading.Lock()

    def add(self, live: LiveSession) -> None:
        with self._lock:
            self._sessions[live.ctx.session_id] = live

    def get(self, session_id: uuid.UUID) -> LiveSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def consume_ticket(self, session_id: uuid.UUID, ticket: str | None) -> LiveSession:
        """The session for a valid, unused, unexpired ticket. Raises with the close reason."""
        with self._lock:
            live = self._sessions.get(session_id)
            if live is None:
                raise RealtimeVoiceError("session_not_found")
            if live.ticket_used or not ticket_matches(ticket, live.ticket_hash):
                raise RealtimeVoiceError("signaling_failed", status_code=403)
            if time.monotonic() > live.ticket_expires:
                raise RealtimeVoiceError("session_expired")
            live.ticket_used = True
            return live

    def remove(self, session_id: uuid.UUID) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


manager = SessionManager()
