"""detach durable image history from transient queue rows"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_detach_history_from_queue"
down_revision = "0003_message_attachments"
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _job_foreign_keys() -> list[dict]:
    if not _table_exists("images"):
        return []
    return [
        fk
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("images")
        if fk.get("constrained_columns") == ["job_id"]
    ]


def upgrade() -> None:
    if not _table_exists("images"):
        return
    foreign_keys = _job_foreign_keys()
    with op.batch_alter_table(
        "images",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        for fk in foreign_keys:
            batch_op.drop_constraint(
                fk.get("name") or "fk_images_job_id_jobs",
                type_="foreignkey",
            )
        batch_op.alter_column(
            "job_id",
            existing_type=sa.String(length=32),
            nullable=True,
        )


def downgrade() -> None:
    if not _table_exists("images"):
        return
    # Reattaching is only possible for rows whose source queue entry still
    # exists. Recovered disk-only images intentionally have no job id.
    op.execute(
        sa.text(
            "DELETE FROM images WHERE job_id IS NULL "
            "OR job_id NOT IN (SELECT id FROM jobs)"
        )
    )
    with op.batch_alter_table(
        "images",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.alter_column(
            "job_id",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_images_job_id_jobs",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="CASCADE",
        )
