"""Developer platform: API keys, webhooks, and API fields on usage/error events.

Revision ID: 0016_developer_platform
Revises: 0015_teams_organizations
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_developer_platform"
down_revision: str | None = "0015_teams_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
ONE_OWNER = "(user_id IS NULL) <> (organization_id IS NULL)"


def _owner_columns() -> list[sa.Column]:
    return [
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_owner_columns(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(ONE_OWNER, name="ck_api_keys_one_owner"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"])

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *_owner_columns(),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("secret_salt", sa.String(64), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("events", JSON, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(ONE_OWNER, name="ck_webhook_endpoints_one_owner"),
    )
    op.create_index("ix_webhook_endpoints_user_id", "webhook_endpoints", ["user_id"])
    op.create_index("ix_webhook_endpoints_organization_id", "webhook_endpoints", ["organization_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("webhook_id", sa.Uuid(), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("status", sa.String(12), server_default="pending", nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'delivered', 'failed')", name="ck_webhook_deliveries_status"
        ),
    )
    op.create_index("ix_webhook_deliveries_webhook_created", "webhook_deliveries", ["webhook_id", "created_at"])
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_retry_at"])
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])

    op.add_column("usage_events", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("usage_events", sa.Column("api_key_id", sa.Uuid(), nullable=True))
    op.add_column("usage_events", sa.Column("endpoint", sa.String(200), nullable=True))
    op.add_column("usage_events", sa.Column("status_code", sa.Integer(), nullable=True))
    op.create_index("ix_usage_events_organization_id", "usage_events", ["organization_id"])
    op.create_index("ix_usage_events_api_key_id", "usage_events", ["api_key_id"])
    op.add_column("error_events", sa.Column("request_id", sa.String(40), nullable=True))
    op.create_index("ix_error_events_request_id", "error_events", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_error_events_request_id", table_name="error_events")
    op.drop_column("error_events", "request_id")
    op.drop_index("ix_usage_events_api_key_id", table_name="usage_events")
    op.drop_index("ix_usage_events_organization_id", table_name="usage_events")
    for column in ("status_code", "endpoint", "api_key_id", "organization_id"):
        op.drop_column("usage_events", column)
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("api_keys")
