"""API key management for logged-in users (cookie session): /api/developer/keys."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.developer import keys_service
from app.developer.scopes import SCOPES
from app.models import ApiKey
from app.schemas.developer import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, ApiKeyUpdate, ScopeInfo

router = APIRouter(prefix="/keys", tags=["developer"])


def to_read(key: ApiKey) -> ApiKeyRead:
    return ApiKeyRead(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=list(key.scopes or []),
        owner_type="organization" if key.organization_id else "user",
        organization_id=key.organization_id,
        status=keys_service.status_of(key),  # type: ignore[arg-type]
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@router.get("/scopes", response_model=list[ScopeInfo])
def list_scopes() -> list[ScopeInfo]:
    return [ScopeInfo(scope=name, description=text) for name, text in SCOPES.items()]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_key(data: ApiKeyCreate, user: CurrentUser, db: DbSession) -> ApiKeyCreated:
    """Create a key. The full key is in the response only this once."""
    key, secret = keys_service.create(
        db, user, name=data.name, scopes=data.scopes, expires_at=data.expires_at, organization_id=data.organization_id
    )
    return ApiKeyCreated(**to_read(key).model_dump(), key=secret)


@router.get("", response_model=list[ApiKeyRead])
def list_keys(user: CurrentUser, db: DbSession) -> list[ApiKeyRead]:
    return [to_read(key) for key in keys_service.list_for(db, user)]


@router.get("/{key_id}", response_model=ApiKeyRead)
def get_key(key_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ApiKeyRead:
    return to_read(keys_service.get_manageable(db, user, key_id))


@router.patch("/{key_id}", response_model=ApiKeyRead)
def update_key(key_id: uuid.UUID, data: ApiKeyUpdate, user: CurrentUser, db: DbSession) -> ApiKeyRead:
    key = keys_service.get_manageable(db, user, key_id)
    return to_read(
        keys_service.update(
            db,
            user,
            key,
            name=data.name,
            scopes=data.scopes,
            expires_at=data.expires_at,
            set_expiry="expires_at" in data.model_fields_set,
        )
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(key_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    keys_service.delete(db, user, keys_service.get_manageable(db, user, key_id))


@router.post("/{key_id}/rotate", response_model=ApiKeyCreated)
def rotate_key(key_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ApiKeyCreated:
    """A new secret for this key; the old one stops working immediately."""
    key, secret = keys_service.rotate(db, user, keys_service.get_manageable(db, user, key_id))
    return ApiKeyCreated(**to_read(key).model_dump(), key=secret)


@router.post("/{key_id}/revoke", response_model=ApiKeyRead)
def revoke_key(key_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ApiKeyRead:
    return to_read(keys_service.revoke(db, user, keys_service.get_manageable(db, user, key_id)))
