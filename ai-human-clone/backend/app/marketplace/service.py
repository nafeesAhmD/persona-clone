"""Marketplace use cases: discovery, profiles, favorites, reports, owner settings and
analytics, and admin moderation (docs/phase18/contract.md)."""

import hashlib
import logging
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.analytics.events import record_event
from app.marketplace import categories, queries
from app.marketplace.exceptions import MarketplaceError
from app.marketplace.schemas import (
    AdminCloneMarketplace,
    AdminCloneMarketplaceUpdate,
    AdminMarketplaceClone,
    AdminMarketplaceClonePage,
    AdminReport,
    AdminReportClone,
    AdminReportPage,
    AdminReportUpdate,
    Capabilities,
    CategoryCount,
    CategoryRef,
    DailyCount,
    FavoriteRead,
    MarketplaceCard,
    MarketplacePage,
    MarketplaceProfile,
    OwnerAnalytics,
    OwnerMarketplace,
    OwnerMarketplaceUpdate,
    ReportCreate,
    ReportCreated,
    Requirement,
    TagCount,
)
from app.models import CloneProfile, CloneReport, FavoriteClone, PublicChatSession, User
from app.models.analytics import AnalyticsEvent
from app.services import admin_service, platform_service, public_service
from app.services.errors import InvalidInputError, NotFoundError
from app.services.rate_limit import check_public_rate

logger = logging.getLogger(__name__)

SOURCE = "marketplace"
VIEW_DEDUPE_SECONDS = 30 * 60
TAG_SCAN_LIMIT = 2000  # newest listed clones read for the popular-tags count
OPEN_REPORT_STATUSES = ("open", "reviewing")


def _now() -> datetime:
    return datetime.now(UTC)


def hashed(address: str | None) -> str:
    """A visitor's address is only ever kept or compared as a SHA-256 hash."""
    return hashlib.sha256((address or "unknown").encode()).hexdigest()


def viewer_key(user: User | None, address: str | None) -> str:
    return f"user:{user.id}" if user else f"ip:{hashed(address)}"


def _event(db: Session, event_type: str, *, clone_id=None, user: User | None = None, metadata: dict | None = None):
    """Analytics, after the request succeeded. Never with raw query or report text."""
    try:
        record_event(
            db, event_type, clone_id=clone_id, user_id=user.id if user else None, source=SOURCE, metadata=metadata or {}
        )
    except Exception:  # noqa: BLE001 - analytics must never break browsing
        db.rollback()
        logger.warning("Could not record %s", event_type, exc_info=True)


# --- View de-duplication (one view per viewer per clone per 30 minutes) ---------------------

_seen: dict[tuple[str, uuid.UUID], float] = {}
_seen_lock = threading.Lock()


def _first_view(key: str, clone_id: uuid.UUID) -> bool:
    now = time.monotonic()
    with _seen_lock:
        if len(_seen) > 50_000:  # drop expired entries now and then
            for stale in [k for k, until in _seen.items() if until <= now]:
                del _seen[stale]
        until = _seen.get((key, clone_id))
        if until and until > now:
            return False
        _seen[(key, clone_id)] = now + VIEW_DEDUPE_SECONDS
        return True


def reset_view_dedupe() -> None:
    with _seen_lock:
        _seen.clear()


# --- Cards ---------------------------------------------------------------------------------


def _require_discovery(db: Session) -> None:
    if not platform_service.current(db).public_clone_discovery_enabled:
        raise MarketplaceError("discovery_off")


def _card(clone: CloneProfile, *, chat_on: bool, avatar_ready: bool) -> MarketplaceCard:
    voice = public_service.voice_available(clone)
    avatar = public_service.avatar_settings_allow(clone) and avatar_ready
    category = categories.get(clone.marketplace_category)
    return MarketplaceCard(
        id=clone.id,
        slug=clone.slug,
        name=clone.name,
        profession=clone.profession,
        short_description=clone.short_description,
        tagline=clone.tagline,
        avatar_url=f"/api/public/clones/{clone.slug}/avatar-image" if avatar else clone.avatar_url,
        category=CategoryRef(slug=category.slug, name=category.name) if category else None,
        tags=list(clone.marketplace_tags or []),
        skills=list(clone.skills or []),
        capabilities=Capabilities(
            chat=chat_on and clone.public_chat_enabled,
            voice=chat_on and voice,
            avatar=chat_on and avatar,
            realtime_voice=chat_on and public_service.realtime_voice_available(clone),
        ),
        published_at=clone.published_at,
        featured=clone.featured_rank is not None,
    )


def _cards(db: Session, clones: list[CloneProfile]) -> list[MarketplaceCard]:
    chat_on = platform_service.current(db).public_chat_enabled
    ready = queries.clones_with_ready_avatar(db, [clone.id for clone in clones])
    return [_card(clone, chat_on=chat_on, avatar_ready=clone.id in ready) for clone in clones]


# --- Discovery -------------------------------------------------------------------------------


def search(
    db: Session,
    *,
    q: str | None,
    category: str | None,
    tags: list[str],
    profession: str | None,
    voice: bool | None,
    avatar: bool | None,
    sort: str | None,
    page: int,
    page_size: int,
    user: User | None = None,
    endpoint: str = "list",
) -> MarketplacePage:
    _require_discovery(db)
    query = queries.listed()
    q = (q or "").strip() or None
    relevance = None
    if q:
        query, relevance = queries.apply_search(query, db, q)
    if category:
        query = query.where(CloneProfile.marketplace_category == category)
    for tag in tags:
        query = query.where(queries.tag_condition(tag))
    if profession and profession.strip():
        query = query.where(
            func.lower(func.coalesce(CloneProfile.profession, "")).like(queries.like_pattern(profession), escape="\\")
        )
    if voice is not None:
        query = query.where(queries.voice_condition() if voice else ~queries.voice_condition())
    if avatar is not None:
        query = query.where(queries.avatar_condition() if avatar else ~queries.avatar_condition())

    sort = sort or ("relevance" if q else "newest")
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    newest = (CloneProfile.published_at.desc().nulls_last(), CloneProfile.id)
    featured_first = CloneProfile.featured_rank.is_(None)
    if sort == "popular":
        favorites, sessions = queries.popularity()
        score = func.coalesce(favorites.c.n, 0) + func.coalesce(sessions.c.n, 0)
        query = (
            query.outerjoin(favorites, favorites.c.clone_id == CloneProfile.id)
            .outerjoin(sessions, sessions.c.clone_id == CloneProfile.id)
            .order_by(score.desc(), *newest)
        )
    elif sort == "relevance" and relevance is not None:
        query = query.order_by(relevance.desc(), featured_first, *newest)
    else:
        query = query.order_by(*newest)
    clones = list(db.scalars(query.offset((page - 1) * page_size).limit(page_size)))
    result = MarketplacePage(items=_cards(db, clones), total=total, page=page, page_size=page_size, sort=sort)

    filters = sorted(
        name
        for name, value in (
            ("category", category),
            ("tags", tags),
            ("profession", profession),
            ("voice", voice),
            ("avatar", avatar),
        )
        if value not in (None, [], "")
    )
    if q:
        _event(
            db,
            "marketplace_search_performed",
            user=user,
            metadata={"endpoint": endpoint, "q_length": len(q), "filters": filters, "sort": sort, "results": total},
        )
    if category:
        _event(db, "marketplace_category_viewed", user=user, metadata={"category": category, "results": total})
    return result


def featured(db: Session, limit: int) -> list[MarketplaceCard]:
    _require_discovery(db)
    query = (
        queries.listed()
        .where(CloneProfile.featured_rank.is_not(None))
        .order_by(CloneProfile.featured_rank, CloneProfile.published_at.desc().nulls_last(), CloneProfile.id)
        .limit(limit)
    )
    return _cards(db, list(db.scalars(query)))


def category_counts(db: Session) -> list[CategoryCount]:
    _require_discovery(db)
    listed = queries.listed().subquery()
    counts = dict(
        db.execute(
            select(listed.c.marketplace_category, func.count())
            .where(listed.c.marketplace_category.is_not(None))
            .group_by(listed.c.marketplace_category)
        ).all()
    )
    return [
        CategoryCount(slug=c.slug, name=c.name, description=c.description, count=counts.get(c.slug, 0))
        for c in categories.CATEGORIES
    ]


def popular_tags(db: Session, limit: int) -> list[TagCount]:
    """Tags of the newest TAG_SCAN_LIMIT listed clones (one column, not whole rows)."""
    _require_discovery(db)
    rows = db.scalars(
        queries.listed()
        .with_only_columns(CloneProfile.marketplace_tags)
        .order_by(CloneProfile.published_at.desc().nulls_last(), CloneProfile.id)
        .limit(TAG_SCAN_LIMIT)
    )
    counted = Counter(tag for tags in rows for tag in (tags or []))
    ordered = sorted(counted.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [TagCount(tag=tag, count=count) for tag, count in ordered]


def _listed_by_slug(db: Session, slug: str) -> CloneProfile:
    clone = db.scalar(queries.listed().where(CloneProfile.slug == slug.lower()))
    if clone is None:  # the same answer for unknown, private, unlisted, suspended…
        raise MarketplaceError("not_found")
    return clone


def _listed_by_id(db: Session, clone_id: uuid.UUID) -> CloneProfile:
    clone = db.scalar(queries.listed().where(CloneProfile.id == clone_id))
    if clone is None:
        raise MarketplaceError("not_found")
    return clone


def _favorite_count(db: Session, clone_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(FavoriteClone).where(FavoriteClone.clone_id == clone_id)) or 0


def profile(db: Session, slug: str, *, user: User | None, address: str | None) -> MarketplaceProfile:
    """A listed clone's marketplace profile. Works while discovery is off (like /c/{slug})."""
    clone = _listed_by_slug(db, slug)
    card = _cards(db, [clone])[0]
    is_favorite = bool(
        user
        and db.scalar(
            select(FavoriteClone.id).where(FavoriteClone.user_id == user.id, FavoriteClone.clone_id == clone.id)
        )
    )
    result = MarketplaceProfile(
        **card.model_dump(),
        bio=clone.bio,
        preferred_language=clone.preferred_language,
        favorites=_favorite_count(db, clone.id),
        is_favorite=is_favorite,
        public_url=f"/c/{clone.slug}",
    )
    if _first_view(viewer_key(user, address), clone.id):
        _event(db, "marketplace_clone_viewed", clone_id=clone.id, user=user, metadata={"viewer": "user" if user else "visitor"})
    return result


# --- Favorites -------------------------------------------------------------------------------


def add_favorite(db: Session, user: User, clone_id: uuid.UUID) -> tuple[FavoriteRead, bool]:
    """(favorite, created). Saving twice returns the existing row."""
    clone = _listed_by_id(db, clone_id)
    existing = db.scalar(select(FavoriteClone).where(FavoriteClone.user_id == user.id, FavoriteClone.clone_id == clone.id))
    if existing is not None:
        return FavoriteRead(clone_id=clone.id, created_at=existing.created_at), False
    row = FavoriteClone(user_id=user.id, clone_id=clone.id, created_at=_now())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # a parallel request saved it first: the unique constraint holds
        db.rollback()
        existing = db.scalar(
            select(FavoriteClone).where(FavoriteClone.user_id == user.id, FavoriteClone.clone_id == clone.id)
        )
        return FavoriteRead(clone_id=clone.id, created_at=existing.created_at), False
    _event(db, "marketplace_clone_favorited", clone_id=clone.id, user=user)
    return FavoriteRead(clone_id=clone.id, created_at=row.created_at), True


def remove_favorite(db: Session, user: User, clone_id: uuid.UUID) -> None:
    row = db.scalar(select(FavoriteClone).where(FavoriteClone.user_id == user.id, FavoriteClone.clone_id == clone_id))
    if row is None:
        return
    db.delete(row)
    db.commit()
    _event(db, "marketplace_clone_unfavorited", clone_id=clone_id, user=user)


def favorites(db: Session, user: User, *, page: int, page_size: int) -> MarketplacePage:
    """The user's saved clones that are still listed (other rows are kept, just hidden)."""
    query = (
        queries.listed()
        .join(FavoriteClone, FavoriteClone.clone_id == CloneProfile.id)
        .where(FavoriteClone.user_id == user.id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    clones = list(
        db.scalars(
            query.order_by(FavoriteClone.created_at.desc(), CloneProfile.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return MarketplacePage(items=_cards(db, clones), total=total, page=page, page_size=page_size, sort="saved")


# --- Reports ---------------------------------------------------------------------------------


def report(
    db: Session, slug: str, data: ReportCreate, *, user: User | None, address: str | None
) -> tuple[ReportCreated, bool]:
    """(report, created). Any publicly viewable clone (listed or reachable by link) can be
    reported. One open report per reporter and clone; a few reports per hour."""
    try:
        clone = public_service.get_public_clone(db, slug)
    except NotFoundError as exc:
        raise MarketplaceError("not_found") from exc
    key = None if user else hashed(address)
    mine = CloneReport.reporter_user_id == user.id if user else CloneReport.reporter_key == key
    existing = db.scalar(
        select(CloneReport).where(CloneReport.clone_id == clone.id, CloneReport.status.in_(OPEN_REPORT_STATUSES), mine)
    )
    if existing is not None:
        return ReportCreated(id=existing.id, status=existing.status), False
    check_public_rate("report", f"user:{user.id}" if user else f"ip:{key}")
    row = CloneReport(
        reporter_user_id=user.id if user else None,
        reporter_key=key,
        clone_id=clone.id,
        reason=data.reason,
        description=data.description,
        status="open",
        created_at=_now(),
    )
    db.add(row)
    db.commit()
    _event(db, "marketplace_clone_reported", clone_id=clone.id, user=user, metadata={"reason": data.reason})
    return ReportCreated(id=row.id, status=row.status), True


# --- Owner -----------------------------------------------------------------------------------


def requirements(db: Session, clone: CloneProfile) -> list[Requirement]:
    discovery_on = platform_service.current(db).public_clone_discovery_enabled
    checks = (
        ("public", clone.visibility == "public", "Clone is public"),
        ("active", clone.status == "active", "Clone is active"),
        ("public_chat", clone.public_chat_enabled, "Public chat is on"),
        ("not_disabled", not clone.admin_disabled, "Not disabled by an administrator"),
        ("not_suspended", not clone.marketplace_suspended, "Not suspended from the marketplace"),
        ("discovery_on", discovery_on, "Discovery is on for this platform"),
    )
    return [Requirement(key=key, ok=bool(ok), label=label) for key, ok, label in checks]


def owner_view(db: Session, clone: CloneProfile) -> OwnerMarketplace:
    checks = requirements(db, clone)
    eligible = all(check.ok for check in checks if check.key != "discovery_on")
    discovery_on = next(check.ok for check in checks if check.key == "discovery_on")
    return OwnerMarketplace(
        enabled=clone.marketplace_enabled,
        category=clone.marketplace_category,
        tags=list(clone.marketplace_tags or []),
        short_description=clone.short_description,
        published_at=clone.published_at,
        suspended=clone.marketplace_suspended,  # never the reason
        eligible=eligible,
        listed=clone.marketplace_enabled and eligible and discovery_on and clone.owner.is_active,
        requirements=checks,
        preview=_cards(db, [clone])[0],
        public_url=f"/c/{clone.slug}",
    )


def update_owner(db: Session, clone: CloneProfile, data: OwnerMarketplaceUpdate) -> OwnerMarketplace:
    fields = data.model_fields_set
    publishing = data.enabled is True and not clone.marketplace_enabled
    if publishing:  # all checks before any change
        if not data.confirm_publish:
            raise MarketplaceError("confirmation_required")
        failed = [check.key for check in requirements(db, clone) if not check.ok and check.key != "discovery_on"]
        if failed:
            raise MarketplaceError("not_eligible", extra={"failed": failed})
    if "category" in fields:
        clone.marketplace_category = data.category
    if "tags" in fields:
        clone.marketplace_tags = data.tags or []
    if "short_description" in fields:
        clone.short_description = data.short_description
    if publishing:
        clone.marketplace_enabled = True
        clone.published_at = _now()
    elif data.enabled is False and clone.marketplace_enabled:
        # Removed from discovery only: visibility, public chat and everything else stay.
        clone.marketplace_enabled = False
        clone.published_at = None
    db.commit()
    db.refresh(clone)
    return owner_view(db, clone)


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def owner_analytics(db: Session, clone: CloneProfile, days: int) -> OwnerAnalytics:
    today = _now().date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first, datetime.min.time(), UTC)
    view_day = func.date(AnalyticsEvent.created_at)
    views_by_day = {
        _as_date(day): count
        for day, count in db.execute(
            select(view_day, func.count())
            .where(
                AnalyticsEvent.clone_id == clone.id,
                AnalyticsEvent.event_type == "marketplace_clone_viewed",
                AnalyticsEvent.success.is_(True),
                AnalyticsEvent.created_at >= since,
            )
            .group_by(view_day)
        ).all()
    }
    favorite_day = func.date(FavoriteClone.created_at)
    favorites_by_day = {
        _as_date(day): count
        for day, count in db.execute(
            select(favorite_day, func.count())
            .where(FavoriteClone.clone_id == clone.id, FavoriteClone.created_at >= since)
            .group_by(favorite_day)
        ).all()
    }
    chat_starts = db.scalar(
        select(func.count())
        .select_from(PublicChatSession)
        .where(PublicChatSession.clone_id == clone.id, PublicChatSession.created_at >= since)
    )
    daily = [
        DailyCount(date=day, views=views_by_day.get(day, 0), favorites=favorites_by_day.get(day, 0))
        for day in (first + timedelta(days=offset) for offset in range(days))
    ]
    return OwnerAnalytics(
        days=days,
        views=sum(views_by_day.values()),
        favorites=_favorite_count(db, clone.id),
        public_chat_starts=chat_starts or 0,
        daily=daily,
    )


# --- Admin -----------------------------------------------------------------------------------


def _admin_report(row: CloneReport, clone: CloneProfile, reporter_email: str | None) -> AdminReport:
    return AdminReport(
        id=row.id,
        clone=AdminReportClone(id=clone.id, name=clone.name, slug=clone.slug),
        reporter=reporter_email or "anonymous",
        reason=row.reason,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
        resolution_note=row.resolution_note,
    )


def admin_reports(db: Session, *, status: str | None, page: int, page_size: int) -> AdminReportPage:
    reporter = aliased(User)
    query = (
        select(CloneReport, CloneProfile, reporter.email)
        .join(CloneProfile, CloneProfile.id == CloneReport.clone_id)
        .outerjoin(reporter, reporter.id == CloneReport.reporter_user_id)
    )
    if status:
        query = query.where(CloneReport.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(CloneReport.created_at.desc(), CloneReport.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return AdminReportPage(
        items=[_admin_report(row, clone, email) for row, clone, email in rows], total=total, page=page, page_size=page_size
    )


def admin_update_report(db: Session, admin: User, report_id: uuid.UUID, data: AdminReportUpdate) -> AdminReport:
    row = db.get(CloneReport, report_id)
    if row is None:
        raise MarketplaceError("report_not_found")
    previous = row.status
    row.status = data.status
    if "resolution_note" in data.model_fields_set:
        row.resolution_note = data.resolution_note
    row.reviewed_at = _now()
    row.reviewed_by = admin.id
    admin_service.audit(
        db, admin, "marketplace.report_updated", "clone_report", row.id, {"from": previous, "to": data.status}
    )
    db.commit()
    clone = db.get(CloneProfile, row.clone_id)
    email = db.scalar(select(User.email).where(User.id == row.reporter_user_id)) if row.reporter_user_id else None
    return _admin_report(row, clone, email)


def admin_clones(
    db: Session, *, status: str, q: str | None, page: int, page_size: int
) -> AdminMarketplaceClonePage:
    """Clones that opted in, were suspended or are featured — so administrators can manage
    them without a report. `listed` uses the same predicate as public discovery."""
    open_reports = (
        select(CloneReport.clone_id, func.count().label("n"))
        .where(CloneReport.status.in_(OPEN_REPORT_STATUSES))
        .group_by(CloneReport.clone_id)
        .subquery("open_reports")
    )
    listed = CloneProfile.id.in_(queries.listed_ids())
    query = select(CloneProfile, listed.label("listed"), func.coalesce(open_reports.c.n, 0)).outerjoin(
        open_reports, open_reports.c.clone_id == CloneProfile.id
    )
    query = query.where(
        {
            "listed": listed,
            "suspended": CloneProfile.marketplace_suspended.is_(True),
            "featured": CloneProfile.featured_rank.is_not(None),
            "all": or_(
                CloneProfile.marketplace_enabled.is_(True),
                CloneProfile.marketplace_suspended.is_(True),
                CloneProfile.featured_rank.is_not(None),
            ),
        }[status]
    )
    if q and q.strip():
        pattern = queries.like_pattern(q)
        query = query.where(
            or_(
                func.lower(CloneProfile.name).like(pattern, escape="\\"),
                func.lower(CloneProfile.slug).like(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(CloneProfile.featured_rank.is_(None), CloneProfile.featured_rank, CloneProfile.name, CloneProfile.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        AdminMarketplaceClone(
            id=clone.id,
            name=clone.name,
            slug=clone.slug,
            marketplace_enabled=clone.marketplace_enabled,
            listed=bool(is_listed),
            suspended=clone.marketplace_suspended,
            suspended_reason=clone.marketplace_suspended_reason,
            featured_rank=clone.featured_rank,
            published_at=clone.published_at,
            open_reports=reports,
        )
        for clone, is_listed, reports in rows
    ]
    return AdminMarketplaceClonePage(items=items, total=total, page=page, page_size=page_size)


def admin_update_clone(
    db: Session, admin: User, clone_id: uuid.UUID, data: AdminCloneMarketplaceUpdate
) -> AdminCloneMarketplace:
    """Only the fields present in the body change: setting a featured rank never lifts a
    suspension, and a reason alone only updates the reason of a suspended clone."""
    fields = data.model_fields_set
    if not fields:
        raise InvalidInputError("Send at least one of: suspended, reason, featured_rank.")
    clone = db.get(CloneProfile, clone_id)
    if clone is None:
        raise NotFoundError("AI Clone not found.")
    if data.suspended is not None and data.suspended != clone.marketplace_suspended:
        clone.marketplace_suspended = data.suspended
        clone.marketplace_suspended_reason = data.reason if data.suspended else None
        admin_service.audit(
            db,
            admin,
            "marketplace.clone_suspended" if data.suspended else "marketplace.clone_unsuspended",
            "clone",
            clone.id,
            {"has_reason": bool(data.reason)},
        )
    elif "reason" in fields and clone.marketplace_suspended:
        clone.marketplace_suspended_reason = data.reason
    if "featured_rank" in fields and data.featured_rank != clone.featured_rank:
        clone.featured_rank = data.featured_rank
        admin_service.audit(db, admin, "marketplace.clone_featured", "clone", clone.id, {"rank": data.featured_rank})
    db.commit()
    return AdminCloneMarketplace(
        clone_id=clone.id,
        slug=clone.slug,
        marketplace_enabled=clone.marketplace_enabled,
        suspended=clone.marketplace_suspended,
        suspended_reason=clone.marketplace_suspended_reason,
        featured_rank=clone.featured_rank,
    )
