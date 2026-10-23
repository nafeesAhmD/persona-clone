"""Webhook management for logged-in users (cookie session): /api/developer/webhooks."""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.developer.webhooks import EVENT_DESCRIPTIONS, EVENTS
from app.developer.webhooks import service as webhooks_service
from app.models import WebhookEndpoint
from app.schemas.webhooks import (
    DeliveryPage,
    DeliveryRead,
    WebhookCreate,
    WebhookCreated,
    WebhookEventInfo,
    WebhookRead,
    WebhookTestResult,
    WebhookUpdate,
)

router = APIRouter(prefix="/webhooks", tags=["developer"])


def to_read(endpoint: WebhookEndpoint) -> WebhookRead:
    return WebhookRead(
        id=endpoint.id,
        url=endpoint.url,
        events=list(endpoint.events or []),
        is_active=endpoint.is_active,
        owner_type="organization" if endpoint.organization_id else "user",
        organization_id=endpoint.organization_id,
        failure_count=endpoint.failure_count or 0,
        last_delivery_at=endpoint.last_delivery_at,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


@router.get("/events", response_model=list[WebhookEventInfo])
def list_events() -> list[WebhookEventInfo]:
    return [WebhookEventInfo(event=name, description=EVENT_DESCRIPTIONS[name]) for name in EVENTS]


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
def create_webhook(data: WebhookCreate, user: CurrentUser, db: DbSession) -> WebhookCreated:
    """Register a webhook. The signing secret is in the response only this once."""
    endpoint, secret = webhooks_service.create(
        db, user, url=data.url, events=data.events, organization_id=data.organization_id, is_active=data.is_active
    )
    return WebhookCreated(**to_read(endpoint).model_dump(), secret=secret)


@router.get("", response_model=list[WebhookRead])
def list_webhooks(user: CurrentUser, db: DbSession) -> list[WebhookRead]:
    return [to_read(endpoint) for endpoint in webhooks_service.list_for(db, user)]


@router.get("/{webhook_id}", response_model=WebhookRead)
def get_webhook(webhook_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WebhookRead:
    return to_read(webhooks_service.get_manageable(db, user, webhook_id))


@router.patch("/{webhook_id}", response_model=WebhookRead)
def update_webhook(webhook_id: uuid.UUID, data: WebhookUpdate, user: CurrentUser, db: DbSession) -> WebhookRead:
    endpoint = webhooks_service.get_manageable(db, user, webhook_id)
    return to_read(
        webhooks_service.update(db, user, endpoint, url=data.url, events=data.events, is_active=data.is_active)
    )


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(webhook_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    webhooks_service.delete(db, user, webhooks_service.get_manageable(db, user, webhook_id))


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreated)
def rotate_secret(webhook_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WebhookCreated:
    """A new signing secret; the old one is no longer used."""
    endpoint, secret = webhooks_service.rotate_secret(db, user, webhooks_service.get_manageable(db, user, webhook_id))
    return WebhookCreated(**to_read(endpoint).model_dump(), secret=secret)


@router.post("/{webhook_id}/test", response_model=WebhookTestResult)
def send_test(webhook_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WebhookTestResult:
    """Queue a "webhook.test" event for this webhook (sent by the worker within seconds)."""
    row = webhooks_service.send_test(db, webhooks_service.get_manageable(db, user, webhook_id))
    return WebhookTestResult(delivery_id=row.id, status=row.status)  # type: ignore[arg-type]


@router.get("/{webhook_id}/deliveries", response_model=DeliveryPage)
def list_deliveries(
    webhook_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> DeliveryPage:
    endpoint = webhooks_service.get_manageable(db, user, webhook_id)
    items, total = webhooks_service.list_deliveries(db, endpoint, page=page, limit=limit)
    return DeliveryPage(items=[DeliveryRead.model_validate(item) for item in items], page=page, limit=limit, total=total)


@router.post("/{webhook_id}/deliveries/{delivery_id}/retry", response_model=DeliveryRead)
def retry_delivery(webhook_id: uuid.UUID, delivery_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DeliveryRead:
    """Re-queue a failed delivery (same event id, so the receiver can dedupe)."""
    endpoint = webhooks_service.get_manageable(db, user, webhook_id)
    return DeliveryRead.model_validate(webhooks_service.retry_delivery(db, endpoint, delivery_id))
