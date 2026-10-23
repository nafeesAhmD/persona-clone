from fastapi import APIRouter

from app.org.routes import (
    analytics,
    clones,
    invitations,
    knowledge,
    members,
    memory,
    notifications,
    organizations,
    subscription,
    usage,
)

router = APIRouter()
router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
router.include_router(members.router, prefix="/organizations", tags=["organizations-members"])
router.include_router(invitations.router, tags=["organizations-invitations"])
router.include_router(clones.router, prefix="/organizations", tags=["organizations-clones"])
router.include_router(knowledge.router, tags=["organizations-knowledge"])
router.include_router(memory.router, tags=["organizations-memory"])
router.include_router(usage.router, prefix="/organizations", tags=["organizations-usage"])
router.include_router(subscription.router, prefix="/organizations", tags=["organizations-subscription"])
router.include_router(analytics.router, tags=["organizations-analytics"])
router.include_router(notifications.router, tags=["organizations-notifications"])
__all__ = ["router"]