"""In-app notification service for Phase 13."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    type: str,
    title: str,
    message: str,
    organization_id: Optional[uuid.UUID] = None,
    payload: Optional[dict] = None,
) -> Notification:
    """Create an in-app notification for a user."""
    notif = Notification(
        user_id=user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        message=message,
        payload=payload or {},
    )
    db.add(notif)
    db.flush()
    return notif


def get_user_notifications(
    db: Session,
    user_id: uuid.UUID,
    organization_id: Optional[uuid.UUID] = None,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """Get notifications for a user."""
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if organization_id:
        query = query.filter(Notification.organization_id == organization_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    return query.order_by(Notification.created_at.desc()).limit(limit).offset(offset).all()


def mark_notification_read(db: Session, notification_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Notification]:
    """Mark a notification as read."""
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()
    if notif:
        notif.is_read = True
        db.add(notif)
    return notif


def mark_all_read(db: Session, user_id: uuid.UUID, organization_id: Optional[uuid.UUID] = None) -> int:
    """Mark all notifications as read for a user."""
    query = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    )
    if organization_id:
        query = query.filter(Notification.organization_id == organization_id)
    count = query.count()
    query.update({Notification.is_read: True})
    return count


def delete_notification(db: Session, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Delete a notification."""
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()
    if notif:
        db.delete(notif)
        return True
    return False


ORG_NOTIFICATION_TYPES = {
    "invitation_received": ("New Invitation", "You've been invited to join {org_name} as {role}"),
    "invitation_accepted": ("Invitation Accepted", "{user_name} accepted your invitation to {org_name}"),
    "member_joined": ("New Member", "{user_name} joined {org_name}"),
    "member_removed": ("Member Removed", "{user_name} was removed from {org_name}"),
    "role_changed": ("Role Changed", "Your role in {org_name} was changed to {role}"),
    "clone_shared": ("Clone Shared", "{clone_name} was shared with you in {org_name}"),
    "clone_access_removed": ("Clone Access Removed", "Your access to {clone_name} in {org_name} was removed"),
    "ownership_transferred": ("Ownership Transferred", "Ownership of {org_name} was transferred to {user_name}"),
    "member_left": ("Member Left", "{user_name} left {org_name}"),
}