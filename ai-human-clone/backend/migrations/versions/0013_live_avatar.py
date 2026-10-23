"""Live video-call avatar (Simli): the clone's live face.

Revision ID: 0013_live_avatar
Revises: 0012_admin_monitoring
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_live_avatar"
down_revision: str | None = "0012_admin_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clone_profiles", sa.Column("live_face_id", sa.String(100), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("live_face_status", sa.String(12), server_default="none", nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("live_face_error", sa.String(300), nullable=True))


def downgrade() -> None:
    for column in ("live_face_error", "live_face_status", "live_face_id"):
        op.drop_column("clone_profiles", column)
