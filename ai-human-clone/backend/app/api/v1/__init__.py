"""The public developer API, version 1: /api/v1/*, authenticated with API keys.

Versioning: each version is its own router package (serializers and controllers),
while the business logic stays in app/services, app/ai, app/voice and app/avatar.
A future /api/v2 adds a package next to this one without duplicating that logic.
Errors use the developer format {"error", "message", "request_id"} (see app/main.py).
"""

import json

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from app.api.v1 import agent, analytics, avatar, chat, clones, conversations, search, voice
from app.developer.auth import ApiAuth

ERROR_RESPONSES = {
    400: {"description": "invalid_request / validation_error"},
    401: {"description": "authentication_failed: missing, invalid, revoked or expired API key"},
    403: {"description": "permission_denied: the key lacks a scope, or the account is disabled"},
    404: {"description": "resource_not_found"},
    429: {"description": "rate_limit_exceeded or usage_limit_reached (see Retry-After)"},
}

v1_router = APIRouter(prefix="/v1", responses=ERROR_RESPONSES)


class KeyInfo(BaseModel):
    name: str
    owner_type: str
    scopes: list[str]
    rate_limit_per_minute: int


@v1_router.get("/me", response_model=KeyInfo, tags=["Authentication"], summary="Check an API key")
def whoami(principal: ApiAuth) -> KeyInfo:
    """Returns the calling key's name, owner type, scopes and per-minute rate limit."""
    return KeyInfo(
        name=principal.key_name,
        owner_type="organization" if principal.organization_id else "user",
        scopes=sorted(principal.scopes),
        rate_limit_per_minute=principal.rate_limit_per_minute,
    )


for module in (clones, chat, conversations, search, voice, avatar, analytics, agent):
    v1_router.include_router(module.router)


def developer_openapi(app: FastAPI) -> dict:
    """OpenAPI for /api/v1 only: the internal app APIs are not part of the developer API."""
    cached = getattr(app.state, "developer_openapi", None)
    if cached is not None:
        return cached
    full = get_openapi(title=app.title, version=app.version, routes=app.routes)
    paths = {path: item for path, item in full.get("paths", {}).items() if path.startswith("/api/v1/")}
    paths.pop("/api/v1/openapi.json", None)
    paths.pop("/api/v1/docs", None)
    schemas = full.get("components", {}).get("schemas", {})
    schema = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "Clone Me Developer API",
            "version": "1.0.0",
            "description": (
                "Call your AI Clones from your own apps. Authenticate every request with "
                "`Authorization: Bearer <API key>`. Errors are JSON "
                '`{"error": code, "message": text, "request_id": "req_..."}`; every response '
                "has an `X-Request-ID` header."
            ),
        },
        "paths": paths,
        "components": {"schemas": _referenced(paths, schemas)},
    }
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["ApiKeyAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "description": "API key from /developer/keys, e.g. `ahc_live_...`.",
    }
    schema["security"] = [{"ApiKeyAuth": []}]
    app.state.developer_openapi = schema
    return schema


def _referenced(paths: dict, schemas: dict) -> dict:
    """Only the component schemas the developer endpoints use (internal ones stay hidden)."""
    wanted: dict = {}
    pending = [paths]
    while pending:
        text = json.dumps(pending.pop())
        for name in schemas:
            if name not in wanted and f'"#/components/schemas/{name}"' in text:
                wanted[name] = schemas[name]
                pending.append(schemas[name])
    return wanted
