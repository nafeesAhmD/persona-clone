"""SQL building blocks: the listing predicate, search, capabilities and ranking.

Everything is a SQLAlchemy expression with bound parameters (no string-built SQL). The
search text is public profile metadata only.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, Text, and_, case, cast, exists, false, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CloneAvatar, CloneProfile, FavoriteClone, PublicChatSession, User

POPULAR_WINDOW_DAYS = 30


def listed_conditions() -> list:
    """A clone is listed only when every one of these holds (docs/phase18/contract.md)."""
    return [
        CloneProfile.visibility == "public",
        CloneProfile.status == "active",
        CloneProfile.admin_disabled.is_(False),
        CloneProfile.public_chat_enabled.is_(True),
        CloneProfile.marketplace_enabled.is_(True),
        CloneProfile.marketplace_suspended.is_(False),
        User.is_active.is_(True),
    ]


def listed() -> Select:
    """select(CloneProfile) of listed clones (joined to the owner for is_active)."""
    return select(CloneProfile).join(User, User.id == CloneProfile.owner_id).where(*listed_conditions())


def listed_ids() -> Select:
    return select(CloneProfile.id).join(User, User.id == CloneProfile.owner_id).where(*listed_conditions())


# --- Capabilities (same rules as the public profile, public_service) ---------------------


def voice_condition():
    return and_(
        CloneProfile.public_voice_enabled.is_(True),
        CloneProfile.voice_enabled.is_(True),
        CloneProfile.voice_consent_given.is_(True),
    )


def avatar_condition():
    if not get_settings().avatar_feature_enabled:
        return false()
    ready_avatar = exists().where(
        CloneAvatar.clone_id == CloneProfile.id,
        CloneAvatar.owner_id == CloneProfile.owner_id,
        CloneAvatar.is_active.is_(True),
        CloneAvatar.status == "ready",
    )
    return and_(
        CloneProfile.public_avatar_enabled.is_(True),
        CloneProfile.avatar_enabled.is_(True),
        CloneProfile.avatar_consent_given.is_(True),
        voice_condition(),
        ready_avatar,
    )


def clones_with_ready_avatar(db: Session, clone_ids: list) -> set:
    """One query for a whole page (no N+1): clones whose active avatar is ready."""
    if not clone_ids:
        return set()
    return set(
        db.scalars(
            select(CloneAvatar.clone_id)
            .join(CloneProfile, CloneProfile.id == CloneAvatar.clone_id)
            .where(
                CloneAvatar.clone_id.in_(clone_ids),
                CloneAvatar.owner_id == CloneProfile.owner_id,
                CloneAvatar.is_active.is_(True),
                CloneAvatar.status == "ready",
            )
        )
    )


# --- Search -------------------------------------------------------------------------------


def _space():
    return literal_column("' '")


def search_document():
    """name, short description, tagline, profession, skills, tags and category — public
    metadata only. Must match the GIN index expression in migration 0022 exactly."""
    empty = literal_column("''")
    parts = [
        func.coalesce(CloneProfile.name, empty),
        func.coalesce(CloneProfile.short_description, empty),
        func.coalesce(CloneProfile.tagline, empty),
        func.coalesce(CloneProfile.profession, empty),
        func.coalesce(cast(CloneProfile.skills, Text), empty),
        func.coalesce(cast(CloneProfile.marketplace_tags, Text), empty),
        func.coalesce(CloneProfile.marketplace_category, empty),
    ]
    document = parts[0]
    for part in parts[1:]:
        document = document.op("||")(_space()).op("||")(part)
    return document


def like_pattern(text: str) -> str:
    """A LIKE pattern for a literal substring: %, _ and \\ in the input match themselves."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def apply_search(query: Select, db: Session, q: str):
    """(query filtered by `q`, relevance expression — higher is better)."""
    pattern = like_pattern(q)
    substring = func.lower(search_document()).like(pattern, escape="\\")
    name_match = func.lower(CloneProfile.name).like(pattern, escape="\\")
    if db.get_bind().dialect.name == "postgresql":
        regconfig = literal_column("'simple'::regconfig")
        vector = func.to_tsvector(regconfig, search_document())
        tsquery = func.websearch_to_tsquery(regconfig, q)
        query = query.where(or_(vector.op("@@")(tsquery), substring))
        relevance = func.ts_rank(vector, tsquery) + case((name_match, 1.0), else_=0.0)
    else:
        query = query.where(substring)
        relevance = case((name_match, 1.0), else_=0.0)
    return query, relevance


def tag_condition(tag: str):
    """marketplace_tags contains `tag` (tags never hold quotes, % or _: see schemas.TAG_PATTERN)."""
    return cast(CloneProfile.marketplace_tags, Text).like(like_pattern(f'"{tag}"'), escape="\\")


# --- Ranking ------------------------------------------------------------------------------


def popularity():
    """(favorites + distinct public chat sessions in the last 30 days) per clone, as SQL
    aggregation subqueries joined by the caller. Message volume is deliberately not used."""
    since = datetime.now(UTC) - timedelta(days=POPULAR_WINDOW_DAYS)
    favorites = (
        select(FavoriteClone.clone_id, func.count().label("n"))
        .group_by(FavoriteClone.clone_id)
        .subquery("favorite_counts")
    )
    sessions = (
        select(PublicChatSession.clone_id, func.count(PublicChatSession.id.distinct()).label("n"))
        .where(PublicChatSession.created_at >= since)
        .group_by(PublicChatSession.clone_id)
        .subquery("session_counts")
    )
    return favorites, sessions
