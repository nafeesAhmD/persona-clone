"""Request IDs: every response carries X-Request-ID ("req_" + 24 hex characters).

A safe incoming X-Request-ID (letters, digits, - and _, up to 64) is kept so callers
can trace their own ids; anything else is replaced. The id is stored in error events
and shown in developer API errors, so a developer can report "Request ID: req_..."
without sharing anything sensitive.

Each request is also logged once (logger "app.access"): method, route template (e.g.
/api/clones/{clone_id}), status and duration — never the query string, body or ids.
"""

import logging
import re
import secrets
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging_setup import request_id_var

_SAFE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
access_logger = logging.getLogger("app.access")
# Probes hit these every few seconds: logging them would drown everything else.
_QUIET_PATHS = ("/api/health",)


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


def _route(scope: Scope) -> str:
    """The matched route template with its router prefixes (/api/clones/{clone_id}).
    FastAPI keeps the full template in its effective route context; the route itself
    only knows its own part."""
    context = (scope.get("fastapi") or {}).get("effective_route_context")
    path = getattr(context, "path", None) or getattr(scope.get("route"), "path", None)
    return path or "(unmatched)"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-request-id"), "")
        request_id = incoming if _SAFE.match(incoming) else new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if not scope.get("path", "").startswith(_QUIET_PATHS):
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                route = _route(scope)
                access_logger.info(
                    "%s %s %d %.1fms",
                    scope.get("method", ""),
                    route,
                    status["code"],
                    duration_ms,
                    extra={"method": scope.get("method", ""), "route": route, "status": status["code"], "duration_ms": duration_ms},
                )
            request_id_var.reset(token)
