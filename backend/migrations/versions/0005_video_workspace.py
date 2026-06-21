"""add durable generated video history"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_video_workspace"
down_revision = "0004_detach_history_from_queue"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _table_exists("videos"):
        return
    op.create_table(
        "videos",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("poster_path", sa.String(length=512), nullable=True),
        sa.Column("thumb_path", sa.String(length=512), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frames", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("family", sa.String(length=32), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_videos_job_id", "videos", ["job_id"])
    op.create_index("ix_videos_family", "videos", ["family"])
    op.create_index("ix_videos_created_at", "videos", ["created_at"])


def downgrade() -> None:
    if _table_exists("videos"):
        op.drop_table("videos")
