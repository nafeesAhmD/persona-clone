"""Creating and managing API keys (for logged-in users, from /developer).

- A personal key belongs to its user. An organization key belongs to the
  organization; only its owner/admins can create or manage it, and it stays with the
  organization when the creator leaves.
- The full key is returned only by create and rotate. Afterwards only the display
  prefix ("ahc_live_Ab3dE6gH") is ever shown.
- Scopes must be chosen explicitly; nothing is granted by default.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.developer.scopes import unknown_scopes
from app.developer.secrets import display_prefix, hash_api_key, new_api_key
from app.models import ApiKey, OrganizationAuditLog, OrganizationMember, User
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError

MANAGER_ROLES = {"owner", "admin"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def can_manage_org(db: Session, user: User, organization_id: uuid.UUID) -> bool:
    from app.org.authz.permissions import has_organization_role

    allowed, _ = has_organization_role(db, user.id, organization_id, MANAGER_ROLES)
    return allowed


def managed_org_ids(db: Session, user: User) -> list[uuid.UUID]:
    rows = db.scalars(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user.id, OrganizationMember.status == "active"
        )
    )
    return [org_id for org_id in rows if can_manage_org(db, user, org_id)]


def _org_audit(db: Session, organization_id: uuid.UUID | None, user: User, action: str, key: ApiKey) -> None:
    if organization_id is not None:
        db.add(
            OrganizationAuditLog(
                organization_id=organization_id,
                actor_user_id=user.id,
                action=action,
                target_type="api_key",
                target_id=str(key.id),
            )
        )


def validate_scopes(scopes: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(scopes))
    if not cleaned:
        raise InvalidInputError("Choose at least one scope.")
    unknown = unknown_scopes(cleaned)
    if unknown:
        raise InvalidInputError(f"Unknown scope: {', '.join(unknown)}")
    return cleaned


def validate_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    expires_at = _aware(expires_at)
    now = datetime.now(UTC)
    if expires_at <= now:
        raise InvalidInputError("The expiry date must be in the future.")
    if expires_at > now + timedelta(days=get_settings().api_max_key_expiry_days):
        raise InvalidInputError(f"Keys can be valid for at most {get_settings().api_max_key_expiry_days} days.")
    return expires_at


def create(
    db: Session,
    user: User,
    *,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
    organization_id: uuid.UUID | None = None,
) -> tuple[ApiKey, str]:
    if organization_id is not None and not can_manage_org(db, user, organization_id):
        raise ForbiddenError("Only an organization's owner or admins can create its API keys.")
    secret = new_api_key()
    key = ApiKey(
        user_id=None if organization_id else user.id,
        organization_id=organization_id,
        created_by=user.id,
        name=name.strip(),
        key_prefix=display_prefix(secret),
        key_hash=hash_api_key(secret),
        scopes=validate_scopes(scopes),
        expires_at=validate_expiry(expires_at),
    )
    db.add(key)
    db.flush()
    _org_audit(db, organization_id, user, "api_key.created", key)
    db.commit()
    db.refresh(key)
    return key, secret


def list_for(db: Session, user: User) -> list[ApiKey]:
    orgs = managed_org_ids(db, user)
    condition = ApiKey.user_id == user.id
    if orgs:
        condition = or_(condition, ApiKey.organization_id.in_(orgs))
    return list(db.scalars(select(ApiKey).where(condition).order_by(ApiKey.created_at.desc())))


def get_manageable(db: Session, user: User, key_id: uuid.UUID) -> ApiKey:
    key = db.get(ApiKey, key_id)
    if key is not None:
        if key.user_id == user.id:
            return key
        if key.organization_id is not None and can_manage_org(db, user, key.organization_id):
            return key
    raise NotFoundError("API key not found")


def update(
    db: Session, user: User, key: ApiKey, *, name: str | None, scopes: list[str] | None, expires_at, set_expiry: bool
) -> ApiKey:
    if name is not None:
        key.name = name.strip()
    if scopes is not None:
        key.scopes = validate_scopes(scopes)
    if set_expiry:
        key.expires_at = validate_expiry(expires_at)
    _org_audit(db, key.organization_id, user, "api_key.updated", key)
    db.commit()
    db.refresh(key)
    return key


def rotate(db: Session, user: User, key: ApiKey) -> tuple[ApiKey, str]:
    """A new secret for the same key (name, scopes, owner); the old secret stops at once."""
    if key.revoked_at is not None:
        raise InvalidInputError("A revoked key can't be rotated. Create a new key.")
    secret = new_api_key()
    key.key_prefix = display_prefix(secret)
    key.key_hash = hash_api_key(secret)
    _org_audit(db, key.organization_id, user, "api_key.rotated", key)
    db.commit()
    db.refresh(key)
    return key, secret


def revoke(db: Session, user: User | None, key: ApiKey) -> ApiKey:
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        if user is not None:
            _org_audit(db, key.organization_id, user, "api_key.revoked", key)
        db.commit()
        db.refresh(key)
    return key


def delete(db: Session, user: User, key: ApiKey) -> None:
    _org_audit(db, key.organization_id, user, "api_key.deleted", key)
    db.delete(key)
    db.commit()


def status_of(key: ApiKey) -> str:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and _aware(key.expires_at) <= datetime.now(UTC):
        return "expired"
    return "active"
