"""Add authentication fields to users: username, hashed_password, is_active.

Existing users (created before sign-up existed) get a generated username and an
unusable password marker, so no one can log in as them until a reset flow exists.
Their clones and data are kept.

Revision ID: 0002_user_auth
Revises: 0001_initial
Create Date: 2026-09-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_user_auth"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Not a valid Argon2 hash, so verify_password() always fails for it.
UNUSABLE_PASSWORD = "!"


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("hashed_password", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))

    # Backfill existing rows: "user_" + 12 hex chars of the id is unique and valid.
    op.execute(
        "UPDATE users SET username = 'user_' || substr(replace(id::text, '-', ''), 1, 12) WHERE username IS NULL"
    )
    op.execute(
        sa.text("UPDATE users SET hashed_password = :marker WHERE hashed_password IS NULL").bindparams(
            marker=UNUSABLE_PASSWORD
        )
    )
    # Emails are compared case-insensitively from now on.
    op.execute("UPDATE users SET email = lower(email)")

    op.alter_column("users", "username", nullable=False)
    op.alter_column("users", "hashed_password", nullable=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "is_active")
    op.drop_column("users", "hashed_password")
    op.drop_column("users", "username")
