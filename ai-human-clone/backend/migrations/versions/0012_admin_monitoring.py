"""Administration, security and monitoring.

- users: is_admin (false for everyone; only the CLI/INITIAL_ADMIN_EMAIL grants it),
  failed_login_count / locked_until (temporary login protection), index on is_active.
- clone_profiles.admin_disabled: an administrator's lock the owner can't lift.
- admin_audit_logs, security_events, usage_events, error_events: operational logs.
- platform_settings: one row of platform switches (created with safe defaults).

Revision ID: 0012_admin_monitoring
Revises: 0011_public_clones
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_admin_monitoring"
down_revision: str | None = "0011_public_clones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_is_active", "users", ["is_active"])
    op.add_column(
        "clone_profiles", sa.Column("admin_disabled", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_index("ix_clone_profiles_status", "clone_profiles", ["status"])

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("admin_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("metadata", JSON, nullable=False),
        _created_at(),
    )
    op.create_index("ix_admin_audit_logs_admin_user_id", "admin_audit_logs", ["admin_user_id"])
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index("ix_admin_audit_logs_target", "admin_audit_logs", ["target_type", "target_id"])
    op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("metadata", JSON, nullable=False),
        _created_at(),
    )
    for column in ("event_type", "severity", "user_id", "created_at"):
        op.create_index(f"ix_security_events_{column}", "security_events", [column])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("clone_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("input_units", sa.Float(), nullable=True),
        sa.Column("output_units", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        _created_at(),
    )
    for column in ("user_id", "clone_id", "event_type", "provider", "created_at"):
        op.create_index(f"ix_usage_events_{column}", "usage_events", [column])

    op.create_table(
        "error_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("error_type", sa.String(80), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("endpoint", sa.String(300), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("clone_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.String(300), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        _created_at(),
    )
    for column in ("category", "status_code", "created_at"):
        op.create_index(f"ix_error_events_{column}", "error_events", [column])

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("maintenance_mode", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("public_registration_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("public_clone_discovery_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("public_chat_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("rate_limits", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("INSERT INTO platform_settings (id) VALUES (1)")


def downgrade() -> None:
    for table in ("platform_settings", "error_events", "usage_events", "security_events", "admin_audit_logs"):
        op.drop_table(table)
    op.drop_index("ix_clone_profiles_status", table_name="clone_profiles")
    op.drop_column("clone_profiles", "admin_disabled")
    op.drop_index("ix_users_is_active", table_name="users")
    for column in ("locked_until", "failed_login_count", "is_admin"):
        op.drop_column("users", column)
