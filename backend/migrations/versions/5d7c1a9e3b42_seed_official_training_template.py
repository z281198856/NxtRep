# ruff: noqa: E501
"""seed official exercises and training template

Revision ID: 5d7c1a9e3b42
Revises: 4f2a8e7c91bd
Create Date: 2026-08-26

"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d7c1a9e3b42"
down_revision: str | Sequence[str] | None = "4f2a8e7c91bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXERCISE_IDS = {
    "squat": "10000000-0000-4000-8000-000000000001",
    "bench": "10000000-0000-4000-8000-000000000002",
    "deadlift": "10000000-0000-4000-8000-000000000003",
    "row": "10000000-0000-4000-8000-000000000004",
    "press": "10000000-0000-4000-8000-000000000005",
    "pulldown": "10000000-0000-4000-8000-000000000006",
}
TEMPLATE_ID = "20000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO exercises
            (id, name_zh, movement_pattern, equipment, difficulty)
        VALUES
            ('10000000-0000-4000-8000-000000000001', '杠铃深蹲', 'squat', 'barbell', 'intermediate'),
            ('10000000-0000-4000-8000-000000000002', '杠铃卧推', 'horizontal_push', 'barbell', 'intermediate'),
            ('10000000-0000-4000-8000-000000000003', '传统硬拉', 'hinge', 'barbell', 'intermediate'),
            ('10000000-0000-4000-8000-000000000004', '杠铃划船', 'horizontal_pull', 'barbell', 'intermediate'),
            ('10000000-0000-4000-8000-000000000005', '站姿杠铃推举', 'vertical_push', 'barbell', 'intermediate'),
            ('10000000-0000-4000-8000-000000000006', '高位下拉', 'vertical_pull', 'cable', 'beginner')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO exercise_muscles (exercise_id, muscle_code, role)
        VALUES
            ('10000000-0000-4000-8000-000000000001', 'quadriceps', 'primary'),
            ('10000000-0000-4000-8000-000000000002', 'chest', 'primary'),
            ('10000000-0000-4000-8000-000000000003', 'hamstrings', 'primary'),
            ('10000000-0000-4000-8000-000000000004', 'back', 'primary'),
            ('10000000-0000-4000-8000-000000000005', 'shoulders', 'primary'),
            ('10000000-0000-4000-8000-000000000006', 'back', 'primary')
        ON CONFLICT (exercise_id, muscle_code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO training_templates
            (id, name, goal_types, days_per_week, duration_minutes, equipment, days, is_active)
        VALUES (
            '20000000-0000-4000-8000-000000000001',
            '三天全身训练',
            '["muscle_gain", "strength"]'::jsonb,
            3,
            60,
            '["barbell", "cable"]'::jsonb,
            '[
              {
                "id": "30000000-0000-4000-8000-000000000001",
                "day_index": 1,
                "name": "训练A",
                "estimated_minutes": 60,
                "exercises": [
                  {"id": "31000000-0000-4000-8000-000000000001", "exercise_id": "10000000-0000-4000-8000-000000000001", "order_no": 1, "target_sets": 5, "rep_min": 5, "rep_max": 5, "target_rir": 2, "rest_seconds": 180},
                  {"id": "31000000-0000-4000-8000-000000000002", "exercise_id": "10000000-0000-4000-8000-000000000002", "order_no": 2, "target_sets": 4, "rep_min": 6, "rep_max": 8, "target_rir": 2, "rest_seconds": 150},
                  {"id": "31000000-0000-4000-8000-000000000003", "exercise_id": "10000000-0000-4000-8000-000000000004", "order_no": 3, "target_sets": 4, "rep_min": 8, "rep_max": 10, "target_rir": 2, "rest_seconds": 120}
                ]
              },
              {
                "id": "30000000-0000-4000-8000-000000000002",
                "day_index": 2,
                "name": "训练B",
                "estimated_minutes": 60,
                "exercises": [
                  {"id": "32000000-0000-4000-8000-000000000001", "exercise_id": "10000000-0000-4000-8000-000000000003", "order_no": 1, "target_sets": 3, "rep_min": 5, "rep_max": 5, "target_rir": 2, "rest_seconds": 180},
                  {"id": "32000000-0000-4000-8000-000000000002", "exercise_id": "10000000-0000-4000-8000-000000000005", "order_no": 2, "target_sets": 4, "rep_min": 6, "rep_max": 8, "target_rir": 2, "rest_seconds": 150},
                  {"id": "32000000-0000-4000-8000-000000000003", "exercise_id": "10000000-0000-4000-8000-000000000006", "order_no": 3, "target_sets": 4, "rep_min": 8, "rep_max": 12, "target_rir": 2, "rest_seconds": 120}
                ]
              },
              {
                "id": "30000000-0000-4000-8000-000000000003",
                "day_index": 3,
                "name": "训练C",
                "estimated_minutes": 60,
                "exercises": [
                  {"id": "33000000-0000-4000-8000-000000000001", "exercise_id": "10000000-0000-4000-8000-000000000001", "order_no": 1, "target_sets": 4, "rep_min": 6, "rep_max": 8, "target_rir": 2, "rest_seconds": 150},
                  {"id": "33000000-0000-4000-8000-000000000002", "exercise_id": "10000000-0000-4000-8000-000000000002", "order_no": 2, "target_sets": 4, "rep_min": 8, "rep_max": 10, "target_rir": 2, "rest_seconds": 120},
                  {"id": "33000000-0000-4000-8000-000000000003", "exercise_id": "10000000-0000-4000-8000-000000000004", "order_no": 3, "target_sets": 4, "rep_min": 8, "rep_max": 12, "target_rir": 2, "rest_seconds": 120}
                ]
              }
            ]'::jsonb,
            true
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM training_templates WHERE id = '{TEMPLATE_ID}'")
    exercise_ids = ", ".join(f"'{value}'" for value in EXERCISE_IDS.values())
    op.execute(f"DELETE FROM exercises WHERE id IN ({exercise_ids})")
