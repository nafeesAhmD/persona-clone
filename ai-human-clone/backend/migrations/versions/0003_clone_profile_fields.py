"""Clone profile management fields: slug, tagline, bio, skills list, personality,
response length, visibility, avatar and status.

Existing clones keep all their data:
- `about` is renamed to `bio`.
- comma-separated `skills` text becomes a JSON list.
- each clone gets a unique slug made from its name.
- visibility is set to "public", because every clone was open to chat before
  this migration. New clones default to "private".

Revision ID: 0003_clone_profile
Revises: 0002_user_auth
Create Date: 2026-09-30
"""
import json
import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_clone_profile"
down_revision: str | None = "0002_user_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies: later code changes must not alter what this migration does.
RESPONSE_LENGTHS = ("short", "medium", "detailed")
VISIBILITIES = ("private", "public", "unlisted")
STATUSES = ("draft", "active", "disabled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _slug(name: str, used: set[str]) -> str:
    """Same rules as app/services/slugs.py at the time of this migration."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].rstrip("-") or "clone"
    slug, counter = base, 2
    while slug in used:
        suffix = f"-{counter}"
        slug = f"{base[: 60 - len(suffix)].rstrip('-')}{suffix}"
        counter += 1
    return slug


def upgrade() -> None:
    op.alter_column("clone_profiles", "about", new_column_name="bio")

    op.add_column("clone_profiles", sa.Column("slug", sa.String(60), nullable=True))
    op.add_column("clone_profiles", sa.Column("tagline", sa.String(160), nullable=True))
    op.add_column("clone_profiles", sa.Column("skills_list", JSONB(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column("clone_profiles", sa.Column("personality_description", sa.Text(), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("response_length", sa.String(10), server_default="medium", nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("visibility", sa.String(10), server_default="private", nullable=False))
    op.add_column("clone_profiles", sa.Column("avatar_url", sa.String(500), nullable=True))
    op.add_column("clone_profiles", sa.Column("status", sa.String(10), server_default="active", nullable=False))

    # Backfill existing rows in Python: slugs need uniqueness checks, skills need splitting.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name, skills FROM clone_profiles ORDER BY created_at")).all()
    used: set[str] = set()
    for row in rows:
        slug = _slug(row.name, used)
        used.add(slug)
        skills = [s.strip() for s in (row.skills or "").split(",") if s.strip()]
        bind.execute(
            sa.text(
                "UPDATE clone_profiles SET slug = :slug, skills_list = CAST(:skills AS jsonb), "
                "visibility = 'public' WHERE id = :id"
            ),
            {"slug": slug, "skills": json.dumps(skills), "id": row.id},
        )

    op.drop_column("clone_profiles", "skills")
    op.alter_column("clone_profiles", "skills_list", new_column_name="skills")
    op.alter_column("clone_profiles", "slug", nullable=False)

    op.create_index("ix_clone_profiles_slug", "clone_profiles", ["slug"], unique=True)
    op.create_index("ix_clone_profiles_visibility_status", "clone_profiles", ["visibility", "status"])
    op.create_check_constraint(
        "ck_clone_profiles_response_length", "clone_profiles", _in("response_length", RESPONSE_LENGTHS)
    )
    op.create_check_constraint("ck_clone_profiles_visibility", "clone_profiles", _in("visibility", VISIBILITIES))
    op.create_check_constraint("ck_clone_profiles_status", "clone_profiles", _in("status", STATUSES))


def downgrade() -> None:
    op.drop_constraint("ck_clone_profiles_status", "clone_profiles", type_="check")
    op.drop_constraint("ck_clone_profiles_visibility", "clone_profiles", type_="check")
    op.drop_constraint("ck_clone_profiles_response_length", "clone_profiles", type_="check")
    op.drop_index("ix_clone_profiles_visibility_status", table_name="clone_profiles")
    op.drop_index("ix_clone_profiles_slug", table_name="clone_profiles")

    # Skills back to comma-separated text.
    op.add_column("clone_profiles", sa.Column("skills_text", sa.Text(), nullable=True))
    op.execute(
        "UPDATE clone_profiles SET skills_text = NULLIF(array_to_string(ARRAY("
        "SELECT jsonb_array_elements_text(skills)), ', '), '')"
    )
    op.drop_column("clone_profiles", "skills")
    op.alter_column("clone_profiles", "skills_text", new_column_name="skills")

    for column in (
        "status", "avatar_url", "visibility", "response_length", "personality_description", "tagline", "slug"
    ):
        op.drop_column("clone_profiles", column)
    op.alter_column("clone_profiles", "bio", new_column_name="about")
