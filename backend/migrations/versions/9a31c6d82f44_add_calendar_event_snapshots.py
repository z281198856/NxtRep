"""add calendar event content snapshots and workout reference

Revision ID: 9a31c6d82f44
Revises: 5d7c1a9e3b42
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a31c6d82f44"
down_revision: str | Sequence[str] | None = "5d7c1a9e3b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column("content_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_calendar_events_actual_workout_id_workouts",
        "calendar_events",
        "workouts",
        ["actual_workout_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_calendar_events_estimated_minutes_range"),
        "calendar_events",
        "estimated_minutes BETWEEN 1 AND 300",
    )
    op.create_check_constraint(
        op.f("ck_nutrition_target_drafts_minimums_non_negative"),
        "nutrition_target_drafts",
        "kcal_min >= 0 AND protein_min_g >= 0 AND carbs_min_g >= 0 AND fat_min_g >= 0",
    )
    op.create_check_constraint(
        op.f("ck_nutrition_target_drafts_ranges_ordered"),
        "nutrition_target_drafts",
        "kcal_min <= kcal_max AND protein_min_g <= protein_max_g AND "
        "carbs_min_g <= carbs_max_g AND fat_min_g <= fat_max_g",
    )
    op.drop_constraint(
        op.f("ck_body_measurements_at_least_one_measurement"),
        "body_measurements",
        type_="check",
    )
    op.add_column(
        "body_measurements",
        sa.Column("body_fat_percent", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    op.add_column(
        "body_measurements",
        sa.Column("body_fat_method", sa.String(length=30), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_body_measurements_at_least_one_measurement"),
        "body_measurements",
        "weight_kg IS NOT NULL OR waist_cm IS NOT NULL OR neck_cm IS NOT NULL OR "
        "hip_cm IS NOT NULL OR body_fat_percent IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_body_measurements_body_fat_percent_range"),
        "body_measurements",
        "body_fat_percent IS NULL OR body_fat_percent BETWEEN 1 AND 70",
    )
    op.create_check_constraint(
        op.f("ck_body_measurements_body_fat_method_pair"),
        "body_measurements",
        "(body_fat_percent IS NULL AND body_fat_method IS NULL) OR "
        "(body_fat_percent IS NOT NULL AND body_fat_method IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_body_measurements_measurements_positive"),
        "body_measurements",
        "(weight_kg IS NULL OR weight_kg > 0) AND "
        "(waist_cm IS NULL OR waist_cm > 0) AND "
        "(neck_cm IS NULL OR neck_cm > 0) AND (hip_cm IS NULL OR hip_cm > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_body_measurements_measurements_positive"),
        "body_measurements",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_body_measurements_body_fat_method_pair"),
        "body_measurements",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_body_measurements_body_fat_percent_range"),
        "body_measurements",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_body_measurements_at_least_one_measurement"),
        "body_measurements",
        type_="check",
    )
    op.drop_column("body_measurements", "body_fat_method")
    op.drop_column("body_measurements", "body_fat_percent")
    op.create_check_constraint(
        op.f("ck_body_measurements_at_least_one_measurement"),
        "body_measurements",
        "weight_kg IS NOT NULL OR waist_cm IS NOT NULL OR "
        "neck_cm IS NOT NULL OR hip_cm IS NOT NULL",
    )
    op.drop_constraint(
        op.f("ck_nutrition_target_drafts_ranges_ordered"),
        "nutrition_target_drafts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_nutrition_target_drafts_minimums_non_negative"),
        "nutrition_target_drafts",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_calendar_events_estimated_minutes_range"),
        "calendar_events",
        type_="check",
    )
    op.drop_constraint(
        "fk_calendar_events_actual_workout_id_workouts",
        "calendar_events",
        type_="foreignkey",
    )
    op.drop_column("calendar_events", "content_snapshot")
