"""AI memory indexing fields on documents: indexing_status, indexed_at,
indexing_error, chunk_count.

Existing documents:
- with extracted text -> "not_indexed": they can be (re)indexed from that text.
- ready but without extracted text (uploaded before text was stored) ->
  "indexed", because their vectors were written by the earlier pipeline and
  chat still uses them. They can't be reindexed without re-uploading.

Revision ID: 0005_document_indexing
Revises: 0004_documents
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_document_indexing"
down_revision: str | None = "0004_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXING_STATUSES = ("not_indexed", "indexing", "indexed", "indexing_failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("indexing_status", sa.String(20), server_default="not_indexed", nullable=False)
    )
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("indexing_error", sa.String(500), nullable=True))
    op.add_column("documents", sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False))

    op.execute(
        "UPDATE documents SET indexing_status = 'indexed', indexed_at = updated_at "
        "WHERE status = 'ready' AND extracted_text IS NULL"
    )
    op.create_check_constraint(
        "ck_documents_indexing_status", "documents", _in("indexing_status", INDEXING_STATUSES)
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_indexing_status", "documents", type_="check")
    for column in ("chunk_count", "indexing_error", "indexed_at", "indexing_status"):
        op.drop_column("documents", column)
