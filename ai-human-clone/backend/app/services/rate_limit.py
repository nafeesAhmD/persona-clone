"""A small in-process sliding-window limiter for chat requests.

Good enough for one backend instance. With several instances behind a load
balancer this should move to a shared store (e.g. Redis).
"""

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings
from app.services.platform_service import rate_limit


class RateLimitedError(Exception):
    """Too many requests in the window (mapped to HTTP 429)."""


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, message: str = "You're sending messages too quickly. Please wait a moment.") -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= limit:
                raise RateLimitedError(message)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


chat_limiter = SlidingWindowLimiter()


def check_chat_rate(user_id: object) -> None:
    chat_limiter.check(str(user_id), rate_limit("chat", get_settings().chat_rate_limit_per_minute))


# Voice requests (transcription, voice chat, voice tests) are costlier: their own, lower limit.
voice_limiter = SlidingWindowLimiter()


def check_voice_rate(user_id: object) -> None:
    voice_limiter.check(
        str(user_id),
        rate_limit("voice", get_settings().voice_rate_limit_per_minute),
        "You're sending voice requests too quickly. Please wait a moment.",
    )


# Talking-avatar videos are the most expensive request: a small per-user limit.
avatar_video_limiter = SlidingWindowLimiter()


def check_avatar_video_rate(user_id: object) -> None:
    avatar_video_limiter.check(
        str(user_id),
        rate_limit("avatar_video", get_settings().avatar_video_rate_limit_per_minute),
        "You're creating avatar videos too quickly. Please wait a moment.",
    )


# Anonymous visitors of public clones, keyed by client address (and session).
public_chat_limiter = SlidingWindowLimiter()
public_voice_limiter = SlidingWindowLimiter()
public_avatar_limiter = SlidingWindowLimiter()
public_session_limiter = SlidingWindowLimiter()
# Phase 18 marketplace: browsing (per minute) and reports (per hour).
marketplace_limiter = SlidingWindowLimiter()
marketplace_report_limiter = SlidingWindowLimiter(window_seconds=3600.0)
_BUSY = "Too many requests. Please wait a moment and try again."


def check_public_rate(kind: str, key: str) -> None:
    settings = get_settings()
    limiter, limit = {
        "chat": (public_chat_limiter, rate_limit("public_chat", settings.public_chat_rate_limit_per_minute)),
        "voice": (public_voice_limiter, rate_limit("public_voice", settings.public_voice_rate_limit_per_minute)),
        "avatar": (public_avatar_limiter, rate_limit("public_avatar", settings.public_avatar_rate_limit_per_minute)),
        "session": (public_session_limiter, settings.public_session_rate_limit_per_minute),
        "marketplace": (marketplace_limiter, settings.marketplace_rate_limit_per_minute),
        "report": (marketplace_report_limiter, settings.marketplace_reports_per_hour),
    }[kind]
    limiter.check(key, limit, _BUSY)


def reset_public_limits() -> None:
    for limiter in (
        public_chat_limiter,
        public_voice_limiter,
        public_avatar_limiter,
        public_session_limiter,
        login_limiter,
        marketplace_limiter,
        marketplace_report_limiter,
    ):
        limiter.reset()


# Login attempts, per client address and per email (password guessing).
login_limiter = SlidingWindowLimiter()


def check_login_rate(address: str | None, email: str) -> None:
    limit = rate_limit("login", get_settings().login_rate_limit_per_minute)
    message = "Too many login attempts. Please wait a minute and try again."
    login_limiter.check(f"ip:{address}", limit * 4, message)  # shared networks get some room
    login_limiter.check(f"email:{email}", limit, message)
