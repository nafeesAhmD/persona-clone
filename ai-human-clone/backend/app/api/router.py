from fastapi import APIRouter, Depends

from app.api.admin import admin_router
from app.api.deps import maintenance_guard
from app.api.developer import developer_router
from app.api.v1 import v1_router
from app.api.routes import (
    agent,
    analytics,
    auth,
    avatar,
    billing,
    chat,
    clones,
    documents,
    health,
    live_avatar,
    marketplace,
    memories,
    mobile,
    platform,
    public,
    realtime_voice,
    sharing,
    users,
    voice,
)
from app.org.routes.router import router as org_router

api_router = APIRouter(prefix="/api")
# Always reachable: health, sign-in/out, the platform status banner and the admin area.
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(platform.router)
api_router.include_router(mobile.router)
api_router.include_router(admin_router)
api_router.include_router(org_router)

# Everything else stops (503) while maintenance mode is on, except for administrators.
_guarded = [Depends(maintenance_guard)]
for module in (
    users, clones, documents, chat, memories, voice, avatar, live_avatar, sharing, public, analytics, billing, agent,
    realtime_voice, marketplace,
):
    api_router.include_router(module.router, dependencies=_guarded)
# Developer platform: key/webhook management (cookie session) and the API-key API.
api_router.include_router(developer_router, dependencies=_guarded)
api_router.include_router(v1_router, dependencies=_guarded)

# Phase 17: the real-time voice WebSocket checks maintenance mode itself.
api_router.include_router(realtime_voice.ws_router)
