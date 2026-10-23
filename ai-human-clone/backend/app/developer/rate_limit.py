"""Per-API-key rate limits: per minute (plan-dependent), per hour and a per-second burst.

In-process sliding windows, like the rest of the app's limiters (one backend
instance; move to Redis when running several).
"""

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import get_settings
from app.developer.errors import ApiError


@dataclass(frozen=True)
class Limits:
    per_minute: int
    per_hour: int
    burst: int


@dataclass(frozen=True)
class Allowance:
    limit: int
    remaining: int
    reset_seconds: int


_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def check(key_id: str, limits: Limits) -> Allowance:
    """Count one request for this key, or raise 429 with Retry-After."""
    now = time.monotonic()
    with _lock:
        hits = _hits[key_id]
        while hits and now - hits[0] >= 3600:
            hits.popleft()
        windows = ((1, limits.burst), (60, limits.per_minute), (3600, limits.per_hour))
        for seconds, limit in windows:
            in_window = [t for t in hits if now - t < seconds] if seconds < 3600 else list(hits)
            if len(in_window) >= limit:
                retry = max(1, math.ceil(seconds - (now - in_window[0])))
                raise ApiError(
                    429,
                    "rate_limit_exceeded",
                    "Too many requests.",
                    retry_after=retry,
                    headers={
                        "Retry-After": str(retry),
                        "X-RateLimit-Limit": str(limits.per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry),
                    },
                )
        hits.append(now)
        minute = [t for t in hits if now - t < 60]
        reset = max(1, math.ceil(60 - (now - minute[0]))) if minute else 60
        return Allowance(limit=limits.per_minute, remaining=max(0, limits.per_minute - len(minute)), reset_seconds=reset)


def defaults() -> Limits:
    settings = get_settings()
    return Limits(settings.api_rate_limit_per_minute, settings.api_rate_limit_per_hour, settings.api_rate_limit_burst)


def reset() -> None:
    with _lock:
        _hits.clear()
