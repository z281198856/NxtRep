"""allow archived training plans

Revision ID: 6e1d4b9a2c75
Revises: 2b7e91c4ad60
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6e1d4b9a2c75"
down_revision: str | Sequence[str] | None = "2b7e91c4ad60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_training_plan_versions_status"),
        "training_plan_versions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_training_plan_versions_status"),
        "training_plan_versions",
        "status IN ('active', 'superseded', 'archived')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE training_plan_versions "
        "SET status = 'superseded' "
        "WHERE status = 'archived'"
    )
    op.drop_constraint(
        op.f("ck_training_plan_versions_status"),
        "training_plan_versions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_training_plan_versions_status"),
        "training_plan_versions",
        "status IN ('active', 'superseded')",
    )
