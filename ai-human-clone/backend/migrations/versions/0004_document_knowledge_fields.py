"""Knowledge documents: owner, title, source type, stored file metadata,
extracted text, character count and error message.

Existing documents are kept:
- filename -> original_filename (and used as the title), content_type -> mime_type
- owner_id comes from the document's clone
- status "indexed" becomes "ready"
- their text was never stored in PostgreSQL (only as vectors), so extracted_text
  stays empty and error_message explains that a re-upload shows the text.

Revision ID: 0004_documents
Revises: 0003_clone_profile
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_documents"
down_revision: str | None = "0003_clone_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_TYPES = ("file", "manual_text")
DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")
FILE_TYPES = ("pdf", "docx", "txt", "md")
LEGACY_NOTE = "Uploaded before document text was stored. Upload the file again to view its text."


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.alter_column("documents", "filename", new_column_name="original_filename", nullable=True)
    op.alter_column(
        "documents", "content_type", new_column_name="mime_type", existing_type=sa.String(120), nullable=True
    )
    op.add_column("documents", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("title", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("source_type", sa.String(20), nullable=True))
    op.add_column("documents", sa.Column("stored_filename", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("file_type", sa.String(10), nullable=True))
    op.add_column("documents", sa.Column("file_size", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("character_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("documents", sa.Column("error_message", sa.String(500), nullable=True))

    op.execute(
        "UPDATE documents d SET owner_id = c.owner_id FROM clone_profiles c WHERE c.id = d.clone_id"
    )
    op.execute("UPDATE documents SET title = COALESCE(original_filename, 'Untitled'), source_type = 'file'")
    op.execute(
        "UPDATE documents SET file_type = lower(substring(original_filename from '\\.([A-Za-z0-9]+)$')) "
        "WHERE original_filename IS NOT NULL"
    )
    op.execute(f"UPDATE documents SET file_type = NULL WHERE NOT ({_in('file_type', FILE_TYPES)})")
    op.execute("UPDATE documents SET status = 'ready' WHERE status = 'indexed'")
    op.execute(f"UPDATE documents SET status = 'failed' WHERE NOT ({_in('status', DOCUMENT_STATUSES)})")
    op.execute(
        sa.text("UPDATE documents SET error_message = :note WHERE extracted_text IS NULL").bindparams(note=LEGACY_NOTE)
    )

    op.alter_column("documents", "owner_id", nullable=False)
    op.alter_column("documents", "title", nullable=False)
    op.alter_column("documents", "source_type", nullable=False)
    op.alter_column("documents", "status", server_default="pending")

    op.create_foreign_key(
        "documents_owner_id_fkey", "documents", "users", ["owner_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_index("ix_documents_clone_id_created_at", "documents", ["clone_id", "created_at"])
    op.create_check_constraint("ck_documents_source_type", "documents", _in("source_type", SOURCE_TYPES))
    op.create_check_constraint("ck_documents_status", "documents", _in("status", DOCUMENT_STATUSES))
    op.create_check_constraint(
        "ck_documents_file_type", "documents", f"file_type IS NULL OR {_in('file_type', FILE_TYPES)}"
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_file_type", "documents", type_="check")
    op.drop_constraint("ck_documents_status", "documents", type_="check")
    op.drop_constraint("ck_documents_source_type", "documents", type_="check")
    op.drop_index("ix_documents_clone_id_created_at", table_name="documents")
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_constraint("documents_owner_id_fkey", "documents", type_="foreignkey")

    # Manual knowledge has no file; it can't be represented in the old schema.
    op.execute("DELETE FROM documents WHERE source_type = 'manual_text'")
    op.execute("UPDATE documents SET status = 'indexed' WHERE status = 'ready'")
    op.alter_column("documents", "status", server_default=None)
    for column in (
        "error_message", "character_count", "extracted_text", "file_size", "file_type",
        "stored_filename", "source_type", "title", "owner_id",
    ):
        op.drop_column("documents", column)
    op.alter_column("documents", "mime_type", new_column_name="content_type", existing_type=sa.String(120))
    op.execute("UPDATE documents SET original_filename = 'untitled' WHERE original_filename IS NULL")
    op.alter_column("documents", "original_filename", new_column_name="filename", nullable=False)
