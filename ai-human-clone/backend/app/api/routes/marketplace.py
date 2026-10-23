"""Marketplace & clone discovery (Phase 18, docs/phase18/contract.md).

Browsing is public (a login only adds `is_favorite`); favorites need a login; reports may
be anonymous. Owner settings follow get_managed_clone (owner only). Only listed clones
(app/marketplace/queries.listed) are ever returned, with public profile metadata only.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import CurrentUser, DbSession, session_user
from app.core.config import get_settings
from app.marketplace import categories, service
from app.marketplace.schemas import (
    CategoryCount,
    FavoriteRead,
    MarketplaceCard,
    MarketplacePage,
    MarketplaceProfile,
    OwnerAnalytics,
    OwnerMarketplace,
    OwnerMarketplaceUpdate,
    ReportCreate,
    ReportCreated,
    Sort,
    TagCount,
    normalize_tag,
)
from app.models import User
from app.services import clone_service, monitoring
from app.services.errors import InvalidInputError
from app.services.rate_limit import check_public_rate

router = APIRouter(tags=["marketplace"])


def optional_user(request: Request, db: DbSession) -> User | None:
    """The logged-in user if there is a valid session, else None (never an error)."""
    return session_user(db, request.cookies.get(get_settings().auth_cookie_name))


OptionalUser = Annotated[User | None, Depends(optional_user)]


def _browse_limit(request: Request) -> str | None:
    address = monitoring.client_ip(request)
    check_public_rate("marketplace", address or "unknown")
    return address


Address = Annotated[str | None, Depends(_browse_limit)]

Category = Query(default=None, pattern=f"^({'|'.join(categories.SLUGS)})$")
PageNumber = Query(default=1, ge=1, le=1000)
PageSize = Query(default=24, ge=1, le=48)


def _tags(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    try:
        tags = list(dict.fromkeys(normalize_tag(tag) for tag in raw.split(",") if tag.strip()))
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc
    if len(tags) > 5:
        raise InvalidInputError("Use at most 5 tags.")
    return tags


@router.get("/marketplace/clones", response_model=MarketplacePage)
def list_clones(
    db: DbSession,
    user: OptionalUser,
    _address: Address,
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Category,
    tags: str | None = Query(default=None, max_length=200),
    profession: str | None = Query(default=None, max_length=100),
    voice_enabled: bool | None = None,
    avatar_enabled: bool | None = None,
    sort: Sort | None = None,
    page: int = PageNumber,
    page_size: int = PageSize,
) -> MarketplacePage:
    return service.search(
        db,
        q=q,
        category=category,
        tags=_tags(tags),
        profession=profession,
        voice=voice_enabled,
        avatar=avatar_enabled,
        sort=sort,
        page=page,
        page_size=page_size,
        user=user,
    )


@router.get("/marketplace/search", response_model=MarketplacePage)
def search_clones(
    db: DbSession,
    user: OptionalUser,
    _address: Address,
    q: str = Query(min_length=1, max_length=100),
    category: str | None = Category,
    tags: str | None = Query(default=None, max_length=200),
    profession: str | None = Query(default=None, max_length=100),
    voice_enabled: bool | None = None,
    avatar_enabled: bool | None = None,
    sort: Sort = "relevance",
    page: int = PageNumber,
    page_size: int = PageSize,
) -> MarketplacePage:
    if not q.strip():
        raise InvalidInputError("Enter something to search for.")
    return service.search(
        db,
        q=q,
        category=category,
        tags=_tags(tags),
        profession=profession,
        voice=voice_enabled,
        avatar=avatar_enabled,
        sort=sort,
        page=page,
        page_size=page_size,
        user=user,
        endpoint="search",
    )


@router.get("/marketplace/clones/featured", response_model=list[MarketplaceCard])
def featured_clones(db: DbSession, _address: Address, limit: int = Query(default=8, ge=1, le=12)) -> list[MarketplaceCard]:
    return service.featured(db, limit)


@router.get("/marketplace/categories", response_model=list[CategoryCount])
def list_categories(db: DbSession, _address: Address) -> list[CategoryCount]:
    return service.category_counts(db)


@router.get("/marketplace/tags", response_model=list[TagCount])
def list_tags(db: DbSession, _address: Address, limit: int = Query(default=30, ge=1, le=50)) -> list[TagCount]:
    return service.popular_tags(db, limit)


@router.get("/marketplace/clones/{slug}", response_model=MarketplaceProfile)
def clone_profile(slug: str, db: DbSession, user: OptionalUser, address: Address) -> MarketplaceProfile:
    return service.profile(db, slug[:60], user=user, address=address)


@router.post("/marketplace/clones/{slug}/report", response_model=ReportCreated, status_code=status.HTTP_201_CREATED)
def report_clone(
    slug: str, data: ReportCreate, response: Response, db: DbSession, user: OptionalUser, address: Address
) -> ReportCreated:
    created, new = service.report(db, slug[:60], data, user=user, address=address)
    if not new:
        response.status_code = status.HTTP_200_OK
    return created


# --- Favorites (login required) --------------------------------------------------------------


@router.get("/marketplace/favorites", response_model=MarketplacePage)
def list_favorites(
    db: DbSession, user: CurrentUser, page: int = PageNumber, page_size: int = PageSize
) -> MarketplacePage:
    return service.favorites(db, user, page=page, page_size=page_size)


@router.post("/marketplace/favorites/{clone_id}", response_model=FavoriteRead, status_code=status.HTTP_201_CREATED)
def add_favorite(clone_id: uuid.UUID, response: Response, db: DbSession, user: CurrentUser) -> FavoriteRead:
    favorite, created = service.add_favorite(db, user, clone_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return favorite


@router.delete("/marketplace/favorites/{clone_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(clone_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    service.remove_favorite(db, user, clone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Owner -----------------------------------------------------------------------------------


@router.get("/clones/{clone_id}/marketplace", response_model=OwnerMarketplace)
def owner_settings(clone_id: uuid.UUID, db: DbSession, user: CurrentUser) -> OwnerMarketplace:
    return service.owner_view(db, clone_service.get_managed_clone(db, clone_id, user))


@router.patch("/clones/{clone_id}/marketplace", response_model=OwnerMarketplace)
def update_owner_settings(
    clone_id: uuid.UUID, data: OwnerMarketplaceUpdate, db: DbSession, user: CurrentUser
) -> OwnerMarketplace:
    """Publishing (enabled false→true) needs confirm_publish and an eligible clone.
    Turning it off only removes the clone from discovery; nothing else changes."""
    return service.update_owner(db, clone_service.get_managed_clone(db, clone_id, user), data)


@router.get("/clones/{clone_id}/marketplace/analytics", response_model=OwnerAnalytics)
def owner_analytics(
    clone_id: uuid.UUID, db: DbSession, user: CurrentUser, days: int = Query(default=30, ge=1, le=90)
) -> OwnerAnalytics:
    return service.owner_analytics(db, clone_service.get_managed_clone(db, clone_id, user), days)
