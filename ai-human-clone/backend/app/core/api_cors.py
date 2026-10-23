"""CORS for the developer API (/api/v1) only.

Browsers may call /api/v1 from API_ALLOWED_ORIGINS (empty by default: server-to-server).
No credentials are ever allowed here: API keys go in the Authorization header, and
cookies are not used by /api/v1. The app's own frontend CORS (with credentials, for
CORS_ORIGINS/FRONTEND_URL) is unchanged for every other path. Never "*" with credentials.
"""

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"
_HEADERS = "Authorization, Content-Type, X-Request-ID"
_EXPOSE = "X-Request-ID, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset"


class DeveloperApiCorsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/v1"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin-1")
        allowed = origin and origin in get_settings().api_allowed_origins
        if scope["method"] == "OPTIONS" and b"access-control-request-method" in headers:
            if not allowed:
                await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
                return
            response = PlainTextResponse("", status_code=204, headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": _METHODS,
                "Access-Control-Allow-Headers": _HEADERS,
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            })
            await response(scope, receive, send)
            return

        async def send_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Drop whatever the frontend CORS layer added: /api/v1 never allows credentials.
                kept = [(k, v) for k, v in message.get("headers", []) if not k.lower().startswith(b"access-control-")]
                if allowed:
                    kept += [
                        (b"access-control-allow-origin", origin.encode()),
                        (b"access-control-expose-headers", _EXPOSE.encode()),
                        (b"vary", b"Origin"),
                    ]
                message["headers"] = kept
            await send(message)

        await self.app(scope, receive, send_cors)
