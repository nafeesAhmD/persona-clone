"""Administration: platform statistics, account and clone moderation, logs, usage.

Rules kept here (the routes only add `require_admin`):
- Nothing is hard-deleted: users are disabled, clones are disabled (reversible,
  data kept), public content is made private. There are no bulk actions.
- Every change an administrator makes is written to admin_audit_logs in the same
  transaction as the change itself, so one can't happen without the other.
- Admins see metadata and counts, never password hashes, session tokens, document
  text or private conversations. Public memories are shown because visitors' clones
  already use them.
- All filters are bound parameters (SQLAlchemy); LIKE patterns are escaped.
"""

import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION, get_settings
from app.models import (
    AdminAuditLog,
    CloneMemory,
    CloneProfile,
    Conversation,
    Document,
    ErrorEvent,
    Message,
    PublicChatSession,
    SecurityEvent,
    UsageEvent,
    User,
)
from app.schemas import admin as schemas
from app.services import platform_service
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)

SELF_DISABLE = "You can't disable your own account."
ADMIN_DISABLE = "Administrator accounts can't be disabled here. Remove the admin role with the CLI first."
COST_NOTE = (
    "Token counts are estimates (about four characters per token) and costs use the prices "
    "configured in the environment. Check your provider's billing page for exact amounts."
)


# --- Helpers ------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _like(text: str) -> str:
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _count(db: Session, query) -> int:
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def _scalar_count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _date_range(query, column, date_from: date | None, date_to: date | None):
    if date_from:
        query = query.where(column >= datetime.combine(date_from, datetime.min.time(), UTC))
    if date_to:
        query = query.where(column < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC))
    return query


def audit(
    db: Session,
    admin: User,
    action: str,
    target_type: str,
    target_id: object | None = None,
    details: dict | None = None,
) -> None:
    """Add an audit record to the current transaction (the caller commits)."""
    from app.services.monitoring import safe_details

    db.add(
        AdminAuditLog(
            admin_user_id=admin.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=safe_details(details),
            created_at=_now(),
        )
    )


# --- Dashboard ----------------------------------------------------------------------


def dashboard(db: Session) -> schemas.DashboardStats:
    since = _now() - timedelta(hours=24)
    by_visibility = dict(
        db.execute(select(CloneProfile.visibility, func.count()).group_by(CloneProfile.visibility)).all()
    )
    return schemas.DashboardStats(
        total_users=_scalar_count(db, User),
        active_users=_scalar_count(db, User, User.is_active.is_(True)),
        disabled_users=_scalar_count(db, User, User.is_active.is_(False)),
        admin_users=_scalar_count(db, User, User.is_admin.is_(True)),
        total_clones=sum(by_visibility.values()),
        public_clones=by_visibility.get("public", 0),
        unlisted_clones=by_visibility.get("unlisted", 0),
        private_clones=by_visibility.get("private", 0),
        disabled_clones=_scalar_count(db, CloneProfile, CloneProfile.status == "disabled"),
        total_documents=_scalar_count(db, Document),
        total_memories=_scalar_count(db, CloneMemory),
        total_conversations=_scalar_count(db, Conversation),
        total_messages=_scalar_count(db, Message),
        public_sessions=_scalar_count(db, PublicChatSession),
        security_events_24h=_scalar_count(db, SecurityEvent, SecurityEvent.created_at >= since),
        errors_24h=_scalar_count(db, ErrorEvent, ErrorEvent.created_at >= since),
        usage_events_24h=_scalar_count(db, UsageEvent, UsageEvent.created_at >= since),
        maintenance_mode=platform_service.current(db).maintenance_mode,
        health=system_health().services,
    )


# --- Users --------------------------------------------------------------------------

_USER_SORTS = {"created_at": User.created_at, "email": User.email, "username": User.username}


def list_users(
    db: Session,
    *,
    page: int,
    limit: int,
    search: str | None,
    status: str | None,
    sort: str,
    order: str,
) -> schemas.Page[schemas.AdminUserRow]:
    query = select(User)
    if search and search.strip():
        pattern = _like(search)
        query = query.where(
            or_(
                func.lower(User.email).like(pattern, escape="\\"),
                func.lower(User.username).like(pattern, escape="\\"),
                func.lower(func.coalesce(User.full_name, "")).like(pattern, escape="\\"),
            )
        )
    if status == "active":
        query = query.where(User.is_active.is_(True))
    elif status == "disabled":
        query = query.where(User.is_active.is_(False))
    elif status == "admin":
        query = query.where(User.is_admin.is_(True))
    total = _count(db, query)
    column = _USER_SORTS.get(sort, User.created_at)
    query = query.order_by(column.asc() if order == "asc" else column.desc(), User.id)
    users = list(db.scalars(query.offset((page - 1) * limit).limit(limit)))
    counts = dict(
        db.execute(
            select(CloneProfile.owner_id, func.count())
            .where(CloneProfile.owner_id.in_([u.id for u in users]))
            .group_by(CloneProfile.owner_id)
        ).all()
    ) if users else {}
    items = [_user_row(u, counts.get(u.id, 0)) for u in users]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def _user_row(user: User, clone_count: int) -> schemas.AdminUserRow:
    return schemas.AdminUserRow(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
        clone_count=clone_count,
    )


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


def user_detail(db: Session, user_id: uuid.UUID) -> schemas.AdminUserDetail:
    user = _get_user(db, user_id)
    conversation_ids = select(Conversation.id).where(Conversation.user_id == user.id)
    return schemas.AdminUserDetail(
        **_user_row(user, _scalar_count(db, CloneProfile, CloneProfile.owner_id == user.id)).model_dump(),
        updated_at=user.updated_at,
        locked_until=user.locked_until,
        document_count=_scalar_count(db, Document, Document.owner_id == user.id),
        conversation_count=_scalar_count(db, Conversation, Conversation.user_id == user.id),
        message_count=_scalar_count(db, Message, Message.conversation_id.in_(conversation_ids)),
        memory_count=_scalar_count(db, CloneMemory, CloneMemory.owner_id == user.id),
    )


def set_user_status(
    db: Session, admin: User, user_id: uuid.UUID, data: schemas.UserStatusUpdate
) -> schemas.AdminUserDetail:
    """Disable or reactivate an account. A disabled user's next request is refused
    (403), so their session ends; their clones stop answering visitors. Nothing is deleted."""
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise ForbiddenError(SELF_DISABLE)
    if user.is_admin and not data.is_active:
        raise ForbiddenError(ADMIN_DISABLE)
    if user.is_active != data.is_active:
        user.is_active = data.is_active
        if data.is_active:
            user.failed_login_count, user.locked_until = 0, None
        audit(
            db,
            admin,
            "USER_ENABLED" if data.is_active else "USER_DISABLED",
            "user",
            user.id,
            {"reason": data.reason},
        )
        db.commit()
        logger.info("Admin %s set user %s active=%s", admin.id, user.id, data.is_active)
    return user_detail(db, user.id)


# --- Clones -------------------------------------------------------------------------


def _clone_row(clone: CloneProfile, owner_email: str) -> dict:
    return {
        "id": clone.id,
        "name": clone.name,
        "slug": clone.slug,
        "owner_id": clone.owner_id,
        "owner_email": owner_email,
        "visibility": clone.visibility,
        "status": clone.status,
        "admin_disabled": clone.admin_disabled,
        "public_chat_enabled": clone.public_chat_enabled,
        "created_at": clone.created_at,
    }


def list_clones(
    db: Session,
    *,
    page: int,
    limit: int,
    search: str | None,
    visibility: str | None,
    status: str | None,
    owner_id: uuid.UUID | None,
) -> schemas.Page[schemas.AdminCloneRow]:
    query = select(CloneProfile, User.email).join(User, User.id == CloneProfile.owner_id)
    if search and search.strip():
        pattern = _like(search)
        query = query.where(
            or_(
                func.lower(CloneProfile.name).like(pattern, escape="\\"),
                func.lower(CloneProfile.slug).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"),
            )
        )
    if visibility:
        query = query.where(CloneProfile.visibility == visibility)
    if status:
        query = query.where(CloneProfile.status == status)
    if owner_id:
        query = query.where(CloneProfile.owner_id == owner_id)
    total = _count(db, query)
    rows = db.execute(
        query.order_by(CloneProfile.created_at.desc(), CloneProfile.id).offset((page - 1) * limit).limit(limit)
    ).all()
    items = [schemas.AdminCloneRow(**_clone_row(clone, email)) for clone, email in rows]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def _get_clone(db: Session, clone_id: uuid.UUID) -> CloneProfile:
    clone = db.get(CloneProfile, clone_id)
    if clone is None:
        raise NotFoundError("Clone not found")
    return clone


def clone_detail(db: Session, clone_id: uuid.UUID) -> schemas.AdminCloneDetail:
    """Metadata and counts only: no prompts, personality text, documents or messages."""
    clone = _get_clone(db, clone_id)
    owner_email = db.scalar(select(User.email).where(User.id == clone.owner_id)) or ""
    conversation_ids = select(Conversation.id).where(Conversation.clone_id == clone.id)
    return schemas.AdminCloneDetail(
        **_clone_row(clone, owner_email),
        tagline=clone.tagline,
        profession=clone.profession,
        public_voice_enabled=clone.public_voice_enabled,
        public_avatar_enabled=clone.public_avatar_enabled,
        voice_enabled=clone.voice_enabled,
        avatar_enabled=clone.avatar_enabled,
        updated_at=clone.updated_at,
        document_count=_scalar_count(db, Document, Document.clone_id == clone.id),
        public_document_count=_scalar_count(
            db, Document, Document.clone_id == clone.id, Document.visibility == "public"
        ),
        memory_count=_scalar_count(db, CloneMemory, CloneMemory.clone_id == clone.id),
        public_memory_count=_scalar_count(
            db, CloneMemory, CloneMemory.clone_id == clone.id, CloneMemory.visibility == "public"
        ),
        conversation_count=_scalar_count(db, Conversation, Conversation.clone_id == clone.id),
        message_count=_scalar_count(db, Message, Message.conversation_id.in_(conversation_ids)),
        public_session_count=_scalar_count(db, PublicChatSession, PublicChatSession.clone_id == clone.id),
    )


def set_clone_status(
    db: Session, admin: User, clone_id: uuid.UUID, data: schemas.CloneStatusUpdate, *, action_prefix: str = "CLONE"
) -> schemas.AdminCloneDetail:
    """Disable: public chat, voice and avatar stop at once and the owner can't
    re-enable it. Enable: back to active. Data is kept either way."""
    clone = _get_clone(db, clone_id)
    disable = data.status == "disabled"
    if clone.admin_disabled != disable or (disable and clone.status != "disabled"):
        before = clone.status
        clone.status = "disabled" if disable else "active"
        clone.admin_disabled = disable
        audit(
            db,
            admin,
            f"{action_prefix}_DISABLED" if disable else f"{action_prefix}_ENABLED",
            "clone",
            clone.id,
            {"reason": data.reason, "before": before, "after": clone.status},
        )
        db.commit()
        logger.info("Admin %s set clone %s status=%s", admin.id, clone.id, clone.status)
    return clone_detail(db, clone.id)


# --- Content moderation ---------------------------------------------------------------


def public_clones(db: Session, *, page: int, limit: int, search: str | None) -> schemas.Page[schemas.PublicCloneItem]:
    query = (
        select(CloneProfile, User.email)
        .join(User, User.id == CloneProfile.owner_id)
        .where(CloneProfile.visibility.in_(("public", "unlisted")))
    )
    if search and search.strip():
        pattern = _like(search)
        query = query.where(
            or_(
                func.lower(CloneProfile.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(CloneProfile.tagline, "")).like(pattern, escape="\\"),
            )
        )
    total = _count(db, query)
    rows = db.execute(query.order_by(CloneProfile.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    items = [
        schemas.PublicCloneItem(
            id=c.id,
            name=c.name,
            slug=c.slug,
            owner_email=email,
            visibility=c.visibility,
            status=c.status,
            tagline=c.tagline,
            profession=c.profession,
            public_chat_enabled=c.public_chat_enabled,
            created_at=c.created_at,
        )
        for c, email in rows
    ]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def public_documents(db: Session, *, page: int, limit: int) -> schemas.Page[schemas.PublicDocumentItem]:
    query = (
        select(Document, CloneProfile.name, User.email)
        .join(CloneProfile, CloneProfile.id == Document.clone_id)
        .join(User, User.id == Document.owner_id)
        .where(Document.visibility == "public")
    )
    total = _count(db, query)
    rows = db.execute(query.order_by(Document.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    items = [
        schemas.PublicDocumentItem(
            id=d.id,
            title=d.title,
            clone_id=d.clone_id,
            clone_name=name,
            owner_email=email,
            source_type=d.source_type,
            character_count=d.character_count,
            created_at=d.created_at,
        )
        for d, name, email in rows
    ]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def public_memories(db: Session, *, page: int, limit: int) -> schemas.Page[schemas.PublicMemoryItem]:
    query = (
        select(CloneMemory, CloneProfile.name, User.email)
        .join(CloneProfile, CloneProfile.id == CloneMemory.clone_id)
        .join(User, User.id == CloneMemory.owner_id)
        .where(CloneMemory.visibility == "public", CloneMemory.status == "approved")
    )
    total = _count(db, query)
    rows = db.execute(query.order_by(CloneMemory.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    items = [
        schemas.PublicMemoryItem(
            id=m.id,
            clone_id=m.clone_id,
            clone_name=name,
            owner_email=email,
            memory_type=m.memory_type,
            content=m.content,
            created_at=m.created_at,
        )
        for m, name, email in rows
    ]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def make_clone_private(db: Session, admin: User, clone_id: uuid.UUID, reason: str | None) -> None:
    """Remove a clone from public view: visitors' links stop working at once."""
    clone = _get_clone(db, clone_id)
    if clone.visibility != "private":
        before = clone.visibility
        clone.visibility = "private"
        clone.public_chat_enabled = clone.public_voice_enabled = clone.public_avatar_enabled = False
        audit(db, admin, "PUBLIC_CLONE_MADE_PRIVATE", "clone", clone.id, {"reason": reason, "before": before})
        db.commit()


def make_document_private(db: Session, admin: User, document_id: uuid.UUID, reason: str | None) -> None:
    """Public answers stop using it at once (public search reads the allowlist from the database)."""
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.visibility != "private":
        document.visibility = "private"
        audit(
            db, admin, "PUBLIC_DOCUMENT_MADE_PRIVATE", "document", document.id,
            {"reason": reason, "clone_id": str(document.clone_id)},
        )
        db.commit()


def make_memory_private(db: Session, admin: User, memory_id: uuid.UUID, reason: str | None) -> None:
    memory = db.get(CloneMemory, memory_id)
    if memory is None:
        raise NotFoundError("Memory not found")
    if memory.visibility != "private":
        memory.visibility = "private"
        audit(
            db, admin, "PUBLIC_MEMORY_MADE_PRIVATE", "memory", memory.id,
            {"reason": reason, "clone_id": str(memory.clone_id)},
        )
        db.commit()


# --- Logs ---------------------------------------------------------------------------


def security_events(
    db: Session,
    *,
    page: int,
    limit: int,
    event_type: str | None,
    severity: str | None,
    user_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> schemas.Page[schemas.SecurityEventRow]:
    query = select(SecurityEvent)
    if event_type:
        query = query.where(SecurityEvent.event_type == event_type)
    if severity:
        query = query.where(SecurityEvent.severity == severity)
    if user_id:
        query = query.where(SecurityEvent.user_id == user_id)
    query = _date_range(query, SecurityEvent.created_at, date_from, date_to)
    total = _count(db, query)
    rows = db.scalars(query.order_by(SecurityEvent.created_at.desc()).offset((page - 1) * limit).limit(limit))
    items = [schemas.SecurityEventRow.model_validate(r) for r in rows]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def audit_logs(
    db: Session,
    *,
    page: int,
    limit: int,
    action: str | None,
    admin_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> schemas.Page[schemas.AuditLogRow]:
    query = select(AdminAuditLog, User.email).outerjoin(User, User.id == AdminAuditLog.admin_user_id)
    if action:
        query = query.where(AdminAuditLog.action == action)
    if admin_id:
        query = query.where(AdminAuditLog.admin_user_id == admin_id)
    query = _date_range(query, AdminAuditLog.created_at, date_from, date_to)
    total = _count(db, query)
    rows = db.execute(query.order_by(AdminAuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)).all()
    items = []
    for log, email in rows:
        row = schemas.AuditLogRow.model_validate(log)
        row.admin_email = email
        items.append(row)
    return schemas.Page(items=items, page=page, limit=limit, total=total)


def error_events(
    db: Session,
    *,
    page: int,
    limit: int,
    category: str | None,
    status_code: int | None,
    endpoint: str | None,
    date_from: date | None,
    date_to: date | None,
) -> schemas.Page[schemas.ErrorEventRow]:
    query = select(ErrorEvent)
    if category:
        query = query.where(ErrorEvent.category == category)
    if status_code:
        query = query.where(ErrorEvent.status_code == status_code)
    if endpoint and endpoint.strip():
        query = query.where(func.lower(func.coalesce(ErrorEvent.endpoint, "")).like(_like(endpoint), escape="\\"))
    query = _date_range(query, ErrorEvent.created_at, date_from, date_to)
    total = _count(db, query)
    rows = db.scalars(query.order_by(ErrorEvent.created_at.desc()).offset((page - 1) * limit).limit(limit))
    items = [schemas.ErrorEventRow.model_validate(r) for r in rows]
    return schemas.Page(items=items, page=page, limit=limit, total=total)


# --- Usage --------------------------------------------------------------------------


def _unit_prices(event_type: str, provider: str | None) -> tuple[float | None, float | None]:
    """(input price, output price) per unit, or None when not configured."""
    settings = get_settings()
    if event_type == "LLM_REQUEST" and provider == "claude":
        return settings.claude_input_cost_per_unit, settings.claude_output_cost_per_unit
    if event_type == "LLM_REQUEST" and provider == "gemini":
        return settings.gemini_input_cost_per_unit, settings.gemini_output_cost_per_unit
    if event_type == "STT_REQUEST":
        return settings.stt_cost_per_unit, None
    if event_type == "TTS_REQUEST":
        return settings.tts_cost_per_unit, None
    if event_type == "LIVE_CALL":
        return None, settings.live_call_cost_per_unit  # per minute of call
    if event_type == "AVATAR_JOB" and provider not in (None, "local"):
        return None, settings.lipsync_cost_per_unit  # per second of video (output units)
    return None, None


def _cost_configured() -> bool:
    s = get_settings()
    return any(
        v is not None
        for v in (
            s.claude_input_cost_per_unit,
            s.claude_output_cost_per_unit,
            s.gemini_input_cost_per_unit,
            s.gemini_output_cost_per_unit,
            s.stt_cost_per_unit,
            s.tts_cost_per_unit,
            s.lipsync_cost_per_unit,
            s.live_call_cost_per_unit,
        )
    )


def usage_report(db: Session, *, days: int) -> schemas.UsageReport:
    since = _now() - timedelta(days=days)
    in_window = UsageEvent.created_at >= since
    # Cached speech didn't call the provider, so it isn't billed.
    billable = UsageEvent.status != "cached"
    grouped = db.execute(
        select(
            UsageEvent.event_type,
            UsageEvent.provider,
            func.count(),
            func.sum(case((UsageEvent.status == "failed", 1), else_=0)),
            func.sum(case((billable, func.coalesce(UsageEvent.input_units, 0)), else_=0)),
            func.sum(case((billable, func.coalesce(UsageEvent.output_units, 0)), else_=0)),
            func.avg(UsageEvent.duration_ms),
        )
        .where(in_window)
        .group_by(UsageEvent.event_type, UsageEvent.provider)
        .order_by(func.count().desc())
    ).all()
    configured = _cost_configured()
    rows: list[schemas.UsageRow] = []
    total_cost = 0.0
    any_cost = False
    for event_type, provider, count, failed, units_in, units_out, avg_ms in grouped:
        price_in, price_out = _unit_prices(event_type, provider)
        cost = None
        if price_in is not None or price_out is not None:
            cost = round((units_in or 0) * (price_in or 0) + (units_out or 0) * (price_out or 0), 6)
            total_cost += cost
            any_cost = True
        rows.append(
            schemas.UsageRow(
                event_type=event_type,
                provider=provider,
                requests=count,
                failed=int(failed or 0),
                input_units=round(float(units_in or 0), 1),
                output_units=round(float(units_out or 0), 1),
                avg_duration_ms=round(float(avg_ms), 1) if avg_ms is not None else None,
                estimated_cost=cost,
            )
        )
    day = func.date(UsageEvent.created_at)
    per_day = [
        schemas.UsageDay(day=str(d), requests=n)
        for d, n in db.execute(select(day, func.count()).where(in_window).group_by(day).order_by(day)).all()
    ]
    top_users = [
        schemas.TopEntry(id=uid, label=email, requests=n)
        for uid, email, n in db.execute(
            select(UsageEvent.user_id, User.email, func.count())
            .join(User, User.id == UsageEvent.user_id)
            .where(in_window)
            .group_by(UsageEvent.user_id, User.email)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
    ]
    top_clones = [
        schemas.TopEntry(id=cid, label=name, requests=n)
        for cid, name, n in db.execute(
            select(UsageEvent.clone_id, CloneProfile.name, func.count())
            .join(CloneProfile, CloneProfile.id == UsageEvent.clone_id)
            .where(in_window)
            .group_by(UsageEvent.clone_id, CloneProfile.name)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
    ]
    return schemas.UsageReport(
        days=days,
        total_requests=sum(r.requests for r in rows),
        rows=rows,
        per_day=per_day,
        top_users=top_users,
        top_clones=top_clones,
        cost_configured=configured,
        estimated_total_cost=round(total_cost, 4) if configured and any_cost else None,
        note=COST_NOTE,
    )


# --- System health ------------------------------------------------------------------


def system_health() -> schemas.SystemHealth:
    """Status of each dependency. Names and states only, never hosts, keys or errors.
    No provider is called (no tokens or quota are used)."""
    from app.ai.embedding_service import get_embedding_service
    from app.ai.factory import get_llm_provider
    from app.avatar.factory import lipsync_provider_name
    from app.db.session import check_database
    from app.services.qdrant_service import get_qdrant_service
    from app.voice.factory import provider_status

    settings = get_settings()
    items: list[schemas.HealthItem] = [schemas.HealthItem(name="application", status="healthy")]

    items.append(schemas.HealthItem(name="database", status="healthy" if check_database() else "unavailable"))
    try:
        qdrant_ok = get_qdrant_service().health_check()
    except Exception:  # noqa: BLE001 - a status page must not fail
        qdrant_ok = False
    items.append(schemas.HealthItem(name="qdrant", status="healthy" if qdrant_ok else "unavailable"))
    items.append(
        schemas.HealthItem(
            name="embeddings", status="healthy" if get_embedding_service().is_ready else "degraded",
            detail=None if get_embedding_service().is_ready else "Model still loading",
        )
    )
    storage_ok = os.path.isdir(settings.upload_dir) and os.access(settings.upload_dir, os.W_OK)
    items.append(schemas.HealthItem(name="storage", status="healthy" if storage_ok else "unavailable"))

    try:
        llm = get_llm_provider()
        if llm.name == "demo":
            items.append(schemas.HealthItem(name="llm", status="not_configured", detail="Demo mode (no API key)"))
        else:
            items.append(schemas.HealthItem(name="llm", status="healthy", detail=f"{llm.name}: {llm.model_name}"))
    except Exception:  # noqa: BLE001
        items.append(schemas.HealthItem(name="llm", status="unavailable"))

    try:
        voice = provider_status()
    except Exception:  # noqa: BLE001
        voice = {"stt": None, "tts": None}
    for kind in ("stt", "tts"):
        name = voice.get(kind)
        items.append(
            schemas.HealthItem(name=kind, status="healthy" if name else "not_configured", detail=name)
        )
    if not settings.avatar_feature_enabled:
        items.append(schemas.HealthItem(name="lipsync", status="disabled"))
    else:
        lipsync = lipsync_provider_name()
        items.append(
            schemas.HealthItem(name="lipsync", status="healthy" if lipsync else "not_configured", detail=lipsync)
        )

    critical = {"database", "qdrant", "storage"}
    degraded = any(i.name in critical and i.status != "healthy" for i in items)
    return schemas.SystemHealth(
        status="degraded" if degraded else "healthy",
        version=APP_VERSION,
        environment=settings.environment,
        services=items,
    )


# --- Platform settings --------------------------------------------------------------


def _default_limits() -> dict[str, int]:
    settings = get_settings()
    return {name: getattr(settings, attr) for name, attr in platform_service.RATE_LIMIT_KEYS.items()}


def get_platform_settings(db: Session) -> schemas.PlatformSettingsRead:
    row = platform_service.get_row(db)
    return schemas.PlatformSettingsRead(
        maintenance_mode=row.maintenance_mode,
        public_registration_enabled=row.public_registration_enabled,
        public_clone_discovery_enabled=row.public_clone_discovery_enabled,
        public_chat_enabled=row.public_chat_enabled,
        rate_limits={k: int(v) for k, v in (row.rate_limits or {}).items() if k in platform_service.RATE_LIMIT_KEYS},
        default_rate_limits=_default_limits(),
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def update_platform_settings(
    db: Session, admin: User, data: schemas.PlatformSettingsUpdate
) -> schemas.PlatformSettingsRead:
    if not data.limits_valid():
        raise InvalidInputError("Rate limits must be between 1 and 1000 per minute.")
    changes = data.model_dump(exclude_none=True)
    if data.rate_limits is not None:
        changes["rate_limits"] = dict(data.rate_limits)  # keep None values: they remove overrides
    _, changed = platform_service.update(db, changes, admin.id)
    if changed:
        audit(
            db,
            admin,
            "SETTINGS_UPDATED",
            "platform_settings",
            1,
            {key: f"{before} -> {after}" for key, (before, after) in changed.items()},
        )
        if "maintenance_mode" in changed:
            audit(
                db, admin, "MAINTENANCE_ON" if changed["maintenance_mode"][1] else "MAINTENANCE_OFF",
                "platform_settings", 1,
            )
    db.commit()
    platform_service.invalidate()
    return get_platform_settings(db)


def platform_status(db: Session) -> schemas.PlatformStatus:
    from app.services.errors import MAINTENANCE

    snapshot = platform_service.current(db)
    return schemas.PlatformStatus(
        maintenance_mode=snapshot.maintenance_mode,
        public_registration_enabled=snapshot.public_registration_enabled and not snapshot.maintenance_mode,
        public_clone_discovery_enabled=snapshot.public_clone_discovery_enabled,
        public_chat_enabled=snapshot.public_chat_enabled,
        message=MAINTENANCE if snapshot.maintenance_mode else None,
    )
