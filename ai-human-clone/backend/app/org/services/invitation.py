from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.models.teams import OrganizationInvitation


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; PostgreSQL aware ones. Compare both as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_expired(inv: OrganizationInvitation) -> bool:
    return _as_utc(inv.expires_at) <= _now()


def create_invitation(db, organization_id: uuid.UUID, email: str, invited_by: uuid.UUID, role: str, expires_hours: int = 72):
    """Returns (invitation, raw token), or None when a live pending invitation already exists.

    Only the token's hash is stored; the raw token is handed out once."""
    email = email.strip().lower()
    existing = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.status == "pending",
        )
        .all()
    )
    for old in existing:
        if not is_expired(old):
            return None
        old.status = "expired"
        db.add(old)
    token = generate_token()
    inv = OrganizationInvitation(
        organization_id=organization_id,
        email=email,
        invited_by=invited_by,
        role=role,
        token_hash=hash_token(token),
        status="pending",
        expires_at=_now() + timedelta(hours=expires_hours),
    )
    db.add(inv)
    db.flush()
    return inv, token


def find_pending(db, token: str) -> OrganizationInvitation | None:
    """The pending, unexpired invitation for this token (an expired one is marked expired)."""
    inv = (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.token_hash == hash_token(token), OrganizationInvitation.status == "pending")
        .first()
    )
    if not inv or inv.accepted_at is not None:
        return None
    if is_expired(inv):
        inv.status = "expired"
        db.add(inv)
        db.commit()
        return None
    return inv


def accept_invitation(db, token: str, user_id: uuid.UUID):
    """Marks the invitation accepted (the caller checks the email and adds the member)."""
    inv = find_pending(db, token)
    if not inv:
        return None
    inv.status = "accepted"
    inv.accepted_at = _now()
    db.add(inv)
    return inv


def decline_invitation(db, token: str):
    inv = find_pending(db, token)
    if not inv:
        return None
    inv.status = "cancelled"
    db.add(inv)
    return inv


def validate_invitation(db, token: str):
    return db.query(OrganizationInvitation).filter(OrganizationInvitation.token_hash == hash_token(token)).first()
