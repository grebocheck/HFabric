"""add prompt_snippets table (P19.4 prompt library)"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_prompt_snippets"
down_revision = "0001_image_metadata_columns"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(index["name"] == name for index in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _table_exists("prompt_snippets"):
        op.create_table(
            "prompt_snippets",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("name", sa.String(length=128), nullable=False, server_default="Untitled prompt"),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("negative", sa.Text(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _index_exists("prompt_snippets", "ix_prompt_snippets_name"):
        op.create_index("ix_prompt_snippets_name", "prompt_snippets", ["name"])
    if not _index_exists("prompt_snippets", "ix_prompt_snippets_updated_at"):
        op.create_index("ix_prompt_snippets_updated_at", "prompt_snippets", ["updated_at"])
    if not _index_exists("prompt_snippets", "ix_prompt_snippets_created_at"):
        op.create_index("ix_prompt_snippets_created_at", "prompt_snippets", ["created_at"])


def downgrade() -> None:
    if _table_exists("prompt_snippets"):
        op.drop_table("prompt_snippets")
