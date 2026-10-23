"""Marketplace & clone discovery (Phase 18): listing fields, favorites and reports.

Existing clones stay out of the marketplace (marketplace_enabled defaults to false).

Revision ID: 0022_marketplace
Revises: 0021_realtime_voice
Create Date: 2026-10-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_marketplace"
down_revision: str | None = "0021_realtime_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_REASONS = (
    "reason IN ('impersonation', 'unauthorized_voice_or_avatar', 'privacy', "
    "'harmful_or_misleading', 'spam', 'other')"
)
_STATUSES = "status IN ('open', 'reviewing', 'resolved', 'dismissed')"
# Must match app/marketplace/search.py (search_document) exactly for PostgreSQL to use it.
_SEARCH_INDEX = (
    "CREATE INDEX ix_clone_profiles_marketplace_search ON clone_profiles USING gin ("
    "to_tsvector('simple'::regconfig, "
    "coalesce(name, '') || ' ' || coalesce(short_description, '') || ' ' || coalesce(tagline, '') || ' ' || "
    "coalesce(profession, '') || ' ' || coalesce(CAST(skills AS TEXT), '') || ' ' || "
    "coalesce(CAST(marketplace_tags AS TEXT), '') || ' ' || coalesce(marketplace_category, '')))"
)


def upgrade() -> None:
    op.add_column(
        "clone_profiles", sa.Column("marketplace_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("marketplace_category", sa.String(40), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("marketplace_tags", _JSON, server_default=sa.text("'[]'"), nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("short_description", sa.String(200), nullable=True))
    op.add_column("clone_profiles", sa.Column("featured_rank", sa.Integer(), nullable=True))
    op.add_column("clone_profiles", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("marketplace_suspended", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("marketplace_suspended_reason", sa.String(200), nullable=True))
    op.create_index(
        "ix_clone_profiles_marketplace",
        "clone_profiles",
        ["marketplace_enabled", "marketplace_suspended", "visibility", "status"],
    )
    op.create_index("ix_clone_profiles_marketplace_category", "clone_profiles", ["marketplace_category"])
    op.create_index("ix_clone_profiles_published_at", "clone_profiles", ["published_at"])
    op.create_index("ix_clone_profiles_featured_rank", "clone_profiles", ["featured_rank"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_SEARCH_INDEX)

    op.create_table(
        "favorite_clones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "clone_id", name="uq_favorite_clones_user_clone"),
    )
    op.create_index("ix_favorite_clones_clone_id", "favorite_clones", ["clone_id"])
    op.create_index("ix_favorite_clones_user_created", "favorite_clones", ["user_id", "created_at"])

    op.create_table(
        "clone_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reporter_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reporter_key", sa.String(64), nullable=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(12), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
        sa.CheckConstraint(_REASONS, name="ck_clone_reports_reason"),
        sa.CheckConstraint(_STATUSES, name="ck_clone_reports_status"),
    )
    op.create_index("ix_clone_reports_clone_id", "clone_reports", ["clone_id"])
    op.create_index("ix_clone_reports_status_created", "clone_reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_clone_reports_status_created", table_name="clone_reports")
    op.drop_index("ix_clone_reports_clone_id", table_name="clone_reports")
    op.drop_table("clone_reports")
    op.drop_index("ix_favorite_clones_user_created", table_name="favorite_clones")
    op.drop_index("ix_favorite_clones_clone_id", table_name="favorite_clones")
    op.drop_table("favorite_clones")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_clone_profiles_marketplace_search")
    op.drop_index("ix_clone_profiles_featured_rank", table_name="clone_profiles")
    op.drop_index("ix_clone_profiles_published_at", table_name="clone_profiles")
    op.drop_index("ix_clone_profiles_marketplace_category", table_name="clone_profiles")
    op.drop_index("ix_clone_profiles_marketplace", table_name="clone_profiles")
    for column in (
        "marketplace_suspended_reason",
        "marketplace_suspended",
        "published_at",
        "featured_rank",
        "short_description",
        "marketplace_tags",
        "marketplace_category",
        "marketplace_enabled",
    ):
        op.drop_column("clone_profiles", column)
