"""Developer platform management for logged-in users (cookie session): /api/developer/*.

API keys, webhooks and the usage dashboard. The public developer API itself, which
uses API keys, is app/api/v1.
"""

from fastapi import APIRouter

from app.api.developer import keys, usage, webhooks

developer_router = APIRouter(prefix="/developer")
developer_router.include_router(keys.router)
developer_router.include_router(webhooks.router)
developer_router.include_router(usage.router)
