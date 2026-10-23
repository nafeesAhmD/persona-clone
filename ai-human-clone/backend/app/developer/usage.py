"""Records one API_REQUEST usage event per authenticated /api/v1 call (and API_ERROR
for failures), with the key, owner, masked endpoint, status code and duration.
Never the key, request body or message text. Also adds rate-limit headers."""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services import monitoring


class DeveloperApiUsageMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = {"code": 500}
        state = scope.setdefault("state", {})

        async def send_tracked(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                extra = state.get("rate_limit_headers") or {}
                if extra:
                    names = {k.lower() for k, _ in message.get("headers", [])}
                    message["headers"] = list(message.get("headers", [])) + [
                        (k.lower().encode(), v.encode()) for k, v in extra.items() if k.lower().encode() not in names
                    ]
            await send(message)

        try:
            await self.app(scope, receive, send_tracked)
        finally:
            key_id = state.get("api_key_id")
            if key_id is not None:
                path = scope["path"]  # ids are masked when stored
                common = {
                    "user_id": state.get("api_owner_user_id"),
                    "organization_id": state.get("api_organization_id"),
                    "api_key_id": key_id,
                    "clone_id": state.get("api_clone_id"),
                    "endpoint": f"{scope['method']} {path}",
                    "status_code": status["code"],
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "provider": "api",
                }
                ok = status["code"] < 400
                monitoring.usage("API_REQUEST", status="success" if ok else "failed", **common)
                if not ok:
                    monitoring.usage("API_ERROR", status="failed", **common)
