"""add persisted chat message attachments"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_message_attachments"
down_revision = "0002_prompt_snippets"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    if not _table_exists(table):
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _table_exists("messages"):
        return
    if "attachments" not in _columns("messages"):
        with op.batch_alter_table("messages") as batch_op:
            batch_op.add_column(sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    if not _table_exists("messages"):
        return
    if "attachments" in _columns("messages"):
        with op.batch_alter_table("messages") as batch_op:
            batch_op.drop_column("attachments")
