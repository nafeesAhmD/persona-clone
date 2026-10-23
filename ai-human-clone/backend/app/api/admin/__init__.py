"""The admin API (/api/admin/*). Every route depends on require_admin, checked on the
server from the database row; hiding the admin menu in the browser is only cosmetic."""

from fastapi import APIRouter, Depends

from app.api.admin import clones, content, dashboard, developer, marketplace, security, settings, system, usage, users
from app.api.deps import require_admin

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
for module in (dashboard, users, clones, content, security, usage, system, settings, developer, marketplace):
    admin_router.include_router(module.router)
