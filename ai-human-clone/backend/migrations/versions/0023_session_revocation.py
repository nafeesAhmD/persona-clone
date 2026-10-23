"""Session revocation: tokens issued before users.sessions_valid_after are refused.

Revision ID: 0023_session_revocation
Revises: 0022_marketplace

Changing the password sets it, so a stolen or forgotten session on another device stops
working at once instead of renewing itself through /api/auth/me. Existing users get NULL
(no change for current sessions).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_session_revocation"
down_revision: str | None = "0022_marketplace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sessions_valid_after")
