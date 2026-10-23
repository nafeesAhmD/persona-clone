"""ALLOWED_HOSTS: reject requests whose Host header isn't one of ours (host-header injection).

Health probes are exempt: Docker and orchestrators call them by container IP or
127.0.0.1, which an allowlist of public names would refuse. Everything else needs an
allowed host, so internal callers must use an allowed name too — e.g. add the Compose
service name (`backend`) when the frontend renders pages server-side via
http://backend:8000. localhost/127.0.0.1 are always allowed (the container itself).
"""

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

EXEMPT_PATHS = ("/api/health/live", "/api/health/ready")
ALWAYS_ALLOWED = ("localhost", "127.0.0.1")


class HostCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        self.checked = TrustedHostMiddleware(app, allowed_hosts=[*allowed_hosts, *ALWAYS_ALLOWED])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and scope.get("path") in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        await self.checked(scope, receive, send)
