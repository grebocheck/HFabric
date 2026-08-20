"""add indexes for bounded scheduler queue selection"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_queue_selection_indexes"
down_revision = "0006_preset_type_names"
branch_labels = None
depends_on = None

_INDEXES = {
    "ix_jobs_queue_priority_created": ["status", "priority", "created_at"],
    "ix_jobs_queue_model_priority_created": [
        "status",
        "model_id",
        "priority",
        "created_at",
    ],
}


def _existing_indexes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("jobs"):
        return set()
    return {item["name"] for item in inspector.get_indexes("jobs")}


def upgrade() -> None:
    existing = _existing_indexes()
    for name, columns in _INDEXES.items():
        if name not in existing:
            op.create_index(name, "jobs", columns)


def downgrade() -> None:
    existing = _existing_indexes()
    for name in reversed(_INDEXES):
        if name in existing:
            op.drop_index(name, table_name="jobs")
