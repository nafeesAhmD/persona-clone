"""Security headers on every API response.

The API only returns JSON and media, so it can forbid framing, MIME sniffing
and any scripts outright. Public visitor endpoints are never cached by shared
caches (they carry session-specific data).
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"cross-origin-resource-policy", b"same-site"),
]
# JSON/media only: nothing on an API response should ever run or be embedded.
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")  # Swagger UI needs its own scripts


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = list(_HEADERS)
                if not path.startswith(_DOCS_PATHS):
                    extra.append(_API_CSP)
                if path.startswith("/api/public/") and b"cache-control" not in present:
                    extra.append((b"cache-control", b"no-store"))
                headers.extend(item for item in extra if item[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, add_headers)
