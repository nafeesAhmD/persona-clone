"""Managing webhook endpoints (logged-in users, from /developer).

Ownership is the same as for API keys: a personal webhook belongs to its user; an
organization webhook belongs to the organization and only its owner/admins can see
or manage it. Anyone else gets 404.

The signing secret is never stored: only a random salt and a hash. It is re-derived
from the salt and a server key when signing, and returned only by create and rotate.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.developer.keys_service import can_manage_org, managed_org_ids
from app.developer.secrets import hash_secret, new_webhook_salt, webhook_secret
from app.developer.webhooks import delivery as delivery_module
from app.developer.webhooks import ssrf
from app.developer.webhooks.events import TEST_EVENT, unknown_events
from app.models import OrganizationAuditLog, User, WebhookDelivery, WebhookEndpoint
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError

MAX_WEBHOOKS_PER_OWNER = 20
NOT_FOUND = "Webhook not found"


def _audit(db: Session, user: User, endpoint: WebhookEndpoint, action: str) -> None:
    if endpoint.organization_id is not None:
        db.add(
            OrganizationAuditLog(
                organization_id=endpoint.organization_id,
                actor_user_id=user.id,
                action=action,
                target_type="webhook",
                target_id=str(endpoint.id),
            )
        )


def validate_events(events: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(event.strip() for event in events if isinstance(event, str)))
    if not cleaned:
        raise InvalidInputError("Choose at least one event.")
    unknown = unknown_events(cleaned)
    if unknown:
        raise InvalidInputError(f"Unknown event: {', '.join(unknown)}")
    return cleaned


def _set_secret(endpoint: WebhookEndpoint) -> str:
    endpoint.secret_salt = new_webhook_salt()
    secret = webhook_secret(endpoint.id, endpoint.secret_salt)
    endpoint.secret_hash = hash_secret(secret)
    return secret


def _count_for(db: Session, *, user_id: uuid.UUID | None, organization_id: uuid.UUID | None) -> int:
    condition = (
        WebhookEndpoint.organization_id == organization_id
        if organization_id is not None
        else WebhookEndpoint.user_id == user_id
    )
    return db.scalar(select(func.count()).select_from(WebhookEndpoint).where(condition)) or 0


def create(
    db: Session,
    user: User,
    *,
    url: str,
    events: list[str],
    organization_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> tuple[WebhookEndpoint, str]:
    if organization_id is not None and not can_manage_org(db, user, organization_id):
        raise ForbiddenError("Only an organization's owner or admins can create its webhooks.")
    events = validate_events(events)
    url = ssrf.validate_url(url)
    owner_user = None if organization_id else user.id
    if _count_for(db, user_id=owner_user, organization_id=organization_id) >= MAX_WEBHOOKS_PER_OWNER:
        raise InvalidInputError(f"You can have at most {MAX_WEBHOOKS_PER_OWNER} webhooks.")
    endpoint = WebhookEndpoint(
        id=uuid.uuid4(),
        user_id=owner_user,
        organization_id=organization_id,
        created_by=user.id,
        url=url,
        events=events,
        is_active=is_active,
        failure_count=0,
    )
    secret = _set_secret(endpoint)
    db.add(endpoint)
    db.flush()
    _audit(db, user, endpoint, "webhook.created")
    db.commit()
    db.refresh(endpoint)
    return endpoint, secret


def list_for(db: Session, user: User) -> list[WebhookEndpoint]:
    orgs = managed_org_ids(db, user)
    condition = WebhookEndpoint.user_id == user.id
    if orgs:
        condition = or_(condition, WebhookEndpoint.organization_id.in_(orgs))
    return list(db.scalars(select(WebhookEndpoint).where(condition).order_by(WebhookEndpoint.created_at.desc())))


def get_manageable(db: Session, user: User, webhook_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = db.get(WebhookEndpoint, webhook_id)
    if endpoint is not None:
        if endpoint.user_id == user.id:
            return endpoint
        if endpoint.organization_id is not None and can_manage_org(db, user, endpoint.organization_id):
            return endpoint
    raise NotFoundError(NOT_FOUND)


def update(
    db: Session,
    user: User,
    endpoint: WebhookEndpoint,
    *,
    url: str | None = None,
    events: list[str] | None = None,
    is_active: bool | None = None,
) -> WebhookEndpoint:
    if url is not None:
        endpoint.url = ssrf.validate_url(url)
    if events is not None:
        endpoint.events = validate_events(events)
    if is_active is not None:
        if is_active and not endpoint.is_active:
            endpoint.failure_count = 0  # turned back on: start counting afresh
        endpoint.is_active = is_active
    endpoint.updated_at = datetime.now(UTC)
    _audit(db, user, endpoint, "webhook.updated")
    db.commit()
    db.refresh(endpoint)
    return endpoint


def rotate_secret(db: Session, user: User, endpoint: WebhookEndpoint) -> tuple[WebhookEndpoint, str]:
    """A new signing secret; the old one stops being used for the next attempt."""
    secret = _set_secret(endpoint)
    endpoint.updated_at = datetime.now(UTC)
    _audit(db, user, endpoint, "webhook.secret_rotated")
    db.commit()
    db.refresh(endpoint)
    return endpoint, secret


def delete(db: Session, user: User, endpoint: WebhookEndpoint) -> None:
    _audit(db, user, endpoint, "webhook.deleted")
    db.delete(endpoint)
    db.commit()


def send_test(db: Session, endpoint: WebhookEndpoint) -> WebhookDelivery:
    """Queue a "webhook.test" event for this endpoint only, and dispatch it."""
    if not endpoint.is_active:
        raise InvalidInputError("Turn the webhook on before sending a test event.")
    now = datetime.now(UTC)
    payload = delivery_module.envelope(
        delivery_module.new_event_id(),
        TEST_EVENT,
        {"webhook_id": endpoint.id, "message": "This is a test event from Clone Me."},
        now,
    )
    row = WebhookDelivery(
        id=uuid.uuid4(),
        webhook_id=endpoint.id,
        event_id=payload["id"],
        event_type=TEST_EVENT,
        payload=payload,
        status="pending",
        attempts=0,
        created_at=now,
    )
    db.add(row)
    db.commit()
    delivery_module.dispatch()
    db.refresh(row)
    return row


def list_deliveries(
    db: Session, endpoint: WebhookEndpoint, *, page: int, limit: int
) -> tuple[list[WebhookDelivery], int]:
    condition = WebhookDelivery.webhook_id == endpoint.id
    total = db.scalar(select(func.count()).select_from(WebhookDelivery).where(condition)) or 0
    items = db.scalars(
        select(WebhookDelivery)
        .where(condition)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    return list(items), total


def retry_delivery(db: Session, endpoint: WebhookEndpoint, delivery_id: uuid.UUID) -> WebhookDelivery:
    """Put a failed delivery back in the queue (one more attempt, same event id)."""
    row = db.get(WebhookDelivery, delivery_id)
    if row is None or row.webhook_id != endpoint.id:
        raise NotFoundError("Delivery not found")
    if row.status != "failed":
        raise InvalidInputError("Only failed deliveries can be retried.")
    if not endpoint.is_active:
        raise InvalidInputError("Turn the webhook on before retrying.")
    row.status, row.next_retry_at, row.last_error = "pending", None, None
    db.commit()
    delivery_module.dispatch()
    db.refresh(row)
    return row
