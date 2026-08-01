"""scope preset names by preset type"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_preset_type_names"
down_revision = "0005_video_workspace"
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("presets"):
        return
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("presets")
    if any(set(item.get("column_names") or []) == {"type", "name"} for item in constraints):
        return
    name_constraint = next(
        (item for item in constraints if item.get("column_names") == ["name"]),
        None,
    )
    with op.batch_alter_table(
        "presets",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        if name_constraint:
            batch_op.drop_constraint(name_constraint.get("name") or "uq_presets_name", type_="unique")
        batch_op.create_unique_constraint("uq_presets_type_name", ["type", "name"])


def downgrade() -> None:
    if not _table_exists("presets"):
        return
    with op.batch_alter_table(
        "presets",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint("uq_presets_type_name", type_="unique")
        batch_op.create_unique_constraint("uq_presets_name", ["name"])
