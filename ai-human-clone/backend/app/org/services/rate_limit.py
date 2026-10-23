"""Simple in-memory rate limiter for organization endpoints.

Good enough for one backend instance; with several instances this should move
to a shared store (e.g. Redis), like app.services.rate_limit.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Callable

from fastapi import HTTPException, Request, status

from app.org.services.route_guard import guard

# {key: [timestamps]}
_rate_store: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()
_cleanup_interval = 300  # seconds
_last_cleanup = time.monotonic()


def _cleanup(now: float) -> None:
    global _last_cleanup
    if now - _last_cleanup > _cleanup_interval:
        cutoff = now - 86400  # longest window in use
        for key in list(_rate_store.keys()):
            _rate_store[key] = [ts for ts in _rate_store[key] if ts > cutoff]
            if not _rate_store[key]:
                del _rate_store[key]
        _last_cleanup = now


def reset() -> None:
    """Forget every hit (used by tests)."""
    with _lock:
        _rate_store.clear()


def _identity(kwargs: dict[str, Any]) -> str | None:
    """The signed-in user when known (fair behind shared IPs), else the client IP."""
    user = kwargs.get("current_user")
    if user is not None and getattr(user, "id", None) is not None:
        return f"user:{user.id}"
    request = kwargs.get("request")
    if isinstance(request, Request):
        return f"ip:{request.client.host if request.client else 'unknown'}"
    return None


def rate_limit(max_requests: int, window_seconds: int, key_prefix: str = "api") -> Callable:
    """Rate limiter decorator for FastAPI endpoints (sync or async).

    Args:
        max_requests: Maximum requests allowed in the window
        window_seconds: Time window in seconds
        key_prefix: Names the limited action; each action has its own budget
    """

    def check(kwargs: dict[str, Any]) -> None:
        identity = _identity(kwargs)
        if identity is None:
            return
        key = f"{key_prefix}:{identity}"
        now = time.monotonic()
        with _lock:
            _cleanup(now)
            hits = [ts for ts in _rate_store[key] if ts > now - window_seconds]
            if len(hits) >= max_requests:
                _rate_store[key] = hits
                # A plain-string detail: the app's error handler only passes strings through.
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later.",
                    headers={"Retry-After": str(max(1, int(window_seconds - (now - hits[0]))))},
                )
            hits.append(now)
            _rate_store[key] = hits

    def decorator(func: Callable) -> Callable:
        return guard(func, check)

    return decorator


# Specific rate limiters for org endpoints
org_creation_limit = rate_limit(5, 3600, "org_create")  # 5 per hour
invitation_send_limit = rate_limit(20, 3600, "invite_send")  # 20 per hour
invitation_accept_limit = rate_limit(10, 300, "invite_accept")  # 10 per 5 min
member_change_limit = rate_limit(30, 300, "member_change")  # 30 per 5 min
ownership_transfer_limit = rate_limit(2, 86400, "ownership_transfer")  # 2 per day
