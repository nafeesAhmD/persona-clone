"""Wrap a route with a check that runs before it, without changing its kind.

FastAPI runs sync routes in a thread pool and awaits async ones, and it looks
through ``functools.wraps`` to decide which one a route is. So a guard must
stay sync around a sync route and async around an async route.
"""
from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable

Check = Callable[[dict[str, Any]], None]


def guard(func: Callable, check: Check) -> Callable:
    """Return `func` wrapped so that `check(kwargs)` runs first (it raises to refuse)."""
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            check(kwargs)
            return await func(*args, **kwargs)

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        check(kwargs)
        return func(*args, **kwargs)

    return sync_wrapper
