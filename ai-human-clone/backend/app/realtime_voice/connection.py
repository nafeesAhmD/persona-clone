"""The WebSocket of one real-time voice session (protocol: docs/phase17/contract.md).

The socket is opened with a one-time ticket from the session API (never the login
cookie alone), from an allowed Origin. Each utterance or typed message starts a turn
in its own task, so "interrupt" (or speaking again) cancels the answer and its speech
at once. The session ends on "end", a closed socket, the maximum duration or an end
request from the session API; every path releases the turn task and the registry.
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import WebSocket
from starlette.concurrency import run_in_threadpool

from app.ai.base import LLMError
from app.billing.exceptions import UsageLimitError
from app.realtime_voice import permissions, service
from app.realtime_voice.db import open_db
from app.realtime_voice.exceptions import ERRORS, RealtimeVoiceError
from app.realtime_voice.provider_base import RealtimeProvider
from app.realtime_voice.safety import clean_text, origin_allowed, utterance_ok
from app.realtime_voice.session_manager import LiveSession, manager
from app.services import platform_service
from app.services.errors import ForbiddenError, NotFoundError
from app.services.rate_limit import RateLimitedError
from app.voice.base import VoiceError

logger = logging.getLogger(__name__)

CLOSE_BAD_REQUEST = 4400
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_EXPIRED = 4410
CLOSE_TRY_LATER = 1013


def describe_error(exc: BaseException) -> tuple[str, str, str | None]:
    """(code, safe message, provider error category or None) for a failed turn."""
    if isinstance(exc, RealtimeVoiceError):
        return exc.code, exc.message, None
    if isinstance(exc, VoiceError):
        if exc.status_code == 429:
            return "rate_limited", exc.user_message, None
        if exc.status_code < 500:
            return "invalid_audio", exc.user_message, None
        return "provider_unavailable", exc.user_message, "voice"
    if isinstance(exc, LLMError):
        return "provider_unavailable", exc.user_message, "llm"
    if isinstance(exc, RateLimitedError):
        return "rate_limited", str(exc), None
    if isinstance(exc, UsageLimitError):
        return "quota_exceeded", ERRORS["quota_exceeded"][1], None
    if isinstance(exc, (ForbiddenError, NotFoundError)):
        return "forbidden", str(exc), None
    return "provider_unavailable", ERRORS["provider_unavailable"][1], "internal"


class _Connection:
    def __init__(self, websocket: WebSocket, live: LiveSession, provider: RealtimeProvider) -> None:
        self.ws = websocket
        self.live = live
        self.provider = provider
        self.lock = asyncio.Lock()  # an audio header and its binary frame stay together
        self.closed = False
        self.turn = 0
        self.task: asyncio.Task | None = None

    async def send(self, message: dict, payload: bytes | None = None) -> None:
        async with self.lock:
            if self.closed:
                return
            try:
                await self.ws.send_text(json.dumps(message))
                if payload is not None:
                    await self.ws.send_bytes(payload)
            except Exception:  # noqa: BLE001 - the browser went away
                self.closed = True

    # --- turns ------------------------------------------------------------------------

    async def start_turn(self, *, audio: bytes | None, text: str | None) -> None:
        await self.interrupt(reply_always=False)  # barge-in: a new turn replaces the running one
        self.turn += 1
        self.live.extra["turns"] = self.turn
        self.task = asyncio.create_task(self._run(self.turn, audio, text))

    async def interrupt(self, *, reply_always: bool) -> None:
        running = self.task is not None and not self.task.done()
        if running:
            self.task.cancel()
            try:
                await self.task
            except BaseException:  # noqa: BLE001 - cancelled or already reported
                pass
        if running or reply_always:
            await self.send({"type": "interrupted", "turn": self.turn})
            await self.send({"type": "state", "state": "listening"})

    async def _run(self, turn: int, audio: bytes | None, text: str | None) -> None:
        speaking = False

        async def emit(message: dict, payload: bytes | None) -> None:
            nonlocal speaking
            if message.get("type") == "audio" and not speaking:
                speaking = True
                await self.send({"type": "state", "state": "speaking"})
            await self.send(message, payload)

        await self.send({"type": "state", "state": "thinking"})
        try:
            await self.provider.run_turn(self.live.ctx, turn, audio=audio, text=text, emit=emit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure becomes a safe message
            code, message, category = describe_error(exc)
            if category == "internal":
                logger.exception("Real-time voice turn failed")
            else:
                logger.warning("Real-time voice turn failed: %s (%s)", code, type(exc).__name__)
            if category:
                await run_in_threadpool(service.provider_error, self.live.ctx.session_id, category)
            await self.send({"type": "error", "code": code, "message": message, "turn": turn, "fatal": False})
        await self.send({"type": "state", "state": "listening"})

    # --- the socket ---------------------------------------------------------------------

    async def _receive(self) -> tuple[str, int | None]:
        """Read messages until the session should end: (reason, close code or None)."""
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return "disconnect", None
            data = message.get("bytes")
            if data is not None:
                if not utterance_ok(data):
                    await self._error("invalid_audio")
                    continue
                await self.start_turn(audio=data, text=None)
                continue
            try:
                payload = json.loads(message.get("text") or "")
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                await self._error("signaling_failed", fatal=True)
                return "error", CLOSE_BAD_REQUEST
            kind = payload.get("type")
            if kind == "hello":
                await self.send(
                    {
                        "type": "ready",
                        "session_id": str(self.live.ctx.session_id),
                        "conversation_id": str(self.live.ctx.conversation_id) if self.live.ctx.conversation_id else None,
                        "speech_mode": self.live.ctx.speech_mode,
                        "max_duration_seconds": self.live.max_duration_seconds,
                    }
                )
                await self.send({"type": "state", "state": "listening"})
            elif kind == "text":
                text = clean_text(payload.get("text"))
                if text is None:
                    await self._error("invalid_message")
                else:
                    await self.start_turn(audio=None, text=text)
            elif kind == "interrupt":
                await self.interrupt(reply_always=True)
            elif kind == "speech_mode":
                if payload.get("mode") in ("voice", "browser"):
                    self.live.ctx.speech_mode = payload["mode"]  # from the next turn on
                else:
                    await self._error("invalid_message")
            elif kind == "end":
                return "client", None
            elif kind == "ping":
                await self.send({"type": "pong"})
            else:
                await self._error("invalid_message")

    async def _error(self, code: str, *, fatal: bool = False) -> None:
        await self.send({"type": "error", "code": code, "message": ERRORS[code][1], "fatal": fatal})

    async def serve(self) -> tuple[str, str | None]:
        """Run until the end; returns (reason, error code or None)."""
        deadline = time.monotonic() + self.live.max_duration_seconds
        receiver = asyncio.create_task(self._receive())
        ender = asyncio.create_task(self.live.end_event.wait())
        done, _ = await asyncio.wait(
            {receiver, ender}, timeout=max(0.0, deadline - time.monotonic()), return_when=asyncio.FIRST_COMPLETED
        )
        close_code: int | None = 1000
        error_code: str | None = None
        if receiver in done:
            try:
                reason, close_code = receiver.result()
            except Exception:  # noqa: BLE001 - the socket broke
                reason, close_code = "disconnect", None
            if reason == "error":
                error_code = "signaling_failed"
        elif ender in done:
            reason = self.live.end_reason or "client"
        else:
            reason = "max_duration"
        for task in (receiver, ender):
            task.cancel()
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except BaseException:  # noqa: BLE001
                pass
        if reason != "disconnect":
            if reason != "error":
                await self.send({"type": "ended", "reason": reason})
            self.closed = True
            try:
                await self.ws.close(code=close_code or 1000)
            except Exception:  # noqa: BLE001 - already closed
                pass
        return reason, error_code


def _maintenance_on() -> bool:
    with open_db() as db:
        return platform_service.current(db).maintenance_mode


async def _refuse(websocket: WebSocket, session_id: uuid.UUID, close_code: int, code: str) -> None:
    # Accept, then close with the reason: closing before the handshake reaches a browser
    # only as code 1006 (an HTTP 403), so it couldn't tell "expired" from "forbidden".
    await websocket.accept()
    await websocket.close(code=close_code)
    await run_in_threadpool(service.connection_failed, session_id, code)


async def serve(websocket: WebSocket, session_id: uuid.UUID, ticket: str | None) -> None:
    if not origin_allowed(websocket.headers.get("origin")):
        await _refuse(websocket, session_id, CLOSE_FORBIDDEN, "origin_not_allowed")
        return
    try:
        provider = permissions.active_provider()
        live = manager.consume_ticket(session_id, ticket)
    except RealtimeVoiceError as exc:
        close_code = {"session_not_found": CLOSE_NOT_FOUND, "session_expired": CLOSE_EXPIRED}.get(exc.code, CLOSE_FORBIDDEN)
        await _refuse(websocket, session_id, close_code, exc.code)
        return
    if await run_in_threadpool(_maintenance_on):
        manager.remove(session_id)
        await _refuse(websocket, session_id, CLOSE_TRY_LATER, "maintenance")
        return

    await websocket.accept()
    live.loop = asyncio.get_running_loop()
    live.end_event = asyncio.Event()
    live.connected = True
    await run_in_threadpool(service.mark_connected, session_id, live.max_duration_seconds)
    connection = _Connection(websocket, live, provider)
    reason, error_code = "error", "internal"
    try:
        reason, error_code = await connection.serve()
    finally:
        await run_in_threadpool(
            service.mark_finished, session_id, reason, connection.turn, error_code, live.ctx.conversation_id
        )
