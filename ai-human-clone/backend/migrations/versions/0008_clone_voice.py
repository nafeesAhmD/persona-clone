"""Voice settings and voice consent on clone profiles.

Existing clones get voice turned off and no consent, so nothing changes
until the owner opts in. A check constraint makes "voice on without
consent" impossible at the database level.

Revision ID: 0008_clone_voice
Revises: 0007_clone_memories
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_clone_voice"
down_revision: str | None = "0007_clone_memories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clone_profiles", sa.Column("voice_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("clone_profiles", sa.Column("voice_provider", sa.String(40), nullable=True))
    op.add_column("clone_profiles", sa.Column("voice_id", sa.String(100), nullable=True))
    op.add_column("clone_profiles", sa.Column("voice_language", sa.String(10), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("voice_consent_given", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("voice_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_clone_profiles_voice_consent", "clone_profiles", "NOT voice_enabled OR voice_consent_given"
    )


def downgrade() -> None:
    op.drop_constraint("ck_clone_profiles_voice_consent", "clone_profiles", type_="check")
    for column in ("voice_consent_at", "voice_consent_given", "voice_language", "voice_id", "voice_provider", "voice_enabled"):
        op.drop_column("clone_profiles", column)
