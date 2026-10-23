"""Organization notification routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.org.authz.permissions import has_organization_role
from app.org.services.notifications import get_user_notifications, mark_all_read, mark_notification_read

router = APIRouter(prefix="/organizations/{organization_id}/notifications", tags=["organizations-notifications"])


@router.get("")
def list_organization_notifications(
    organization_id: uuid.UUID,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List notifications for the current user in an organization."""
    ok, _ = has_organization_role(db, current_user.id, organization_id, {"owner", "admin", "editor", "viewer"})
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    notifications = get_user_notifications(
        db, current_user.id, organization_id, unread_only, limit, offset
    )
    return [
        {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "payload": n.payload,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]


@router.patch("/{notification_id}/read")
def mark_notification_as_read(
    organization_id: uuid.UUID,
    notification_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a notification as read."""
    ok, _ = has_organization_role(db, current_user.id, organization_id, {"owner", "admin", "editor", "viewer"})
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    notif = mark_notification_read(db, notification_id, current_user.id)
    if not notif or notif.organization_id != organization_id:
        db.rollback()
        raise HTTPException(status_code=404, detail="not_found")
    db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_notifications_read(
    organization_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark all notifications as read for the current user in an organization."""
    ok, _ = has_organization_role(db, current_user.id, organization_id, {"owner", "admin", "editor", "viewer"})
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    count = mark_all_read(db, current_user.id, organization_id)
    db.commit()
    return {"ok": True, "count": count}


@router.delete("/{notification_id}")
def delete_notification(
    organization_id: uuid.UUID,
    notification_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a notification."""
    ok, _ = has_organization_role(db, current_user.id, organization_id, {"owner", "admin", "editor", "viewer"})
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
        Notification.organization_id == organization_id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="not_found")
    db.delete(notif)
    db.commit()
    return {"ok": True}