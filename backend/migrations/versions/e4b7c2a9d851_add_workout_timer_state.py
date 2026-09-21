"""add workout timer state

Revision ID: e4b7c2a9d851
Revises: d2a5b9e3f741
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c2a9d851"
down_revision: str | Sequence[str] | None = "d2a5b9e3f741"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("paused_at", sa.DateTime(timezone=True)))
    op.add_column(
        "workouts",
        sa.Column(
            "total_paused_seconds",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.drop_constraint(op.f("ck_workouts_status"), "workouts", type_="check")
    op.create_check_constraint(
        op.f("ck_workouts_status"),
        "workouts",
        "status IN ('in_progress', 'paused', 'completed', 'interrupted')",
    )
    op.create_check_constraint(
        op.f("ck_workouts_total_paused_seconds_non_negative"),
        "workouts",
        "total_paused_seconds >= 0",
    )
    op.drop_index("uq_workouts_one_active_user", table_name="workouts")
    op.create_index(
        "uq_workouts_one_active_user",
        "workouts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('in_progress', 'paused')"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE workouts SET status = 'in_progress', paused_at = NULL WHERE status = 'paused'"
    )
    op.drop_index("uq_workouts_one_active_user", table_name="workouts")
    op.create_index(
        "uq_workouts_one_active_user",
        "workouts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    op.drop_constraint(
        op.f("ck_workouts_total_paused_seconds_non_negative"),
        "workouts",
        type_="check",
    )
    op.drop_constraint(op.f("ck_workouts_status"), "workouts", type_="check")
    op.create_check_constraint(
        op.f("ck_workouts_status"),
        "workouts",
        "status IN ('in_progress', 'completed', 'interrupted')",
    )
    op.drop_column("workouts", "total_paused_seconds")
    op.drop_column("workouts", "paused_at")
