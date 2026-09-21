"""add extended backend features

Revision ID: c1f4a8d2e630
Revises: a9d3e6f1c427
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1f4a8d2e630"
down_revision: str | Sequence[str] | None = "a9d3e6f1c427"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_and_timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.add_column("foods", sa.Column("barcode", sa.String(64)))
    op.create_index("ix_foods_barcode", "foods", ["barcode"], unique=True)

    op.create_table(
        "recipes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("servings", sa.Numeric(8, 2), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("totals", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.String(2000)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_id_and_timestamps(),
        sa.CheckConstraint("servings > 0", name=op.f("ck_recipes_servings_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_recipes_version_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_recipes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipes")),
    )
    op.create_index("ix_recipes_user_id", "recipes", ["user_id"])
    op.create_index("ix_recipes_user_name", "recipes", ["user_id", "name"])

    op.create_table(
        "exercise_content_feedback",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=False),
        sa.Column("feedback_type", sa.String(30), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        *_id_and_timestamps(),
        sa.CheckConstraint(
            "feedback_type IN ('instruction', 'classification', 'media', 'safety', 'other')",
            name=op.f("ck_exercise_content_feedback_feedback_type"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name=op.f("ck_exercise_content_feedback_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_exercise_content_feedback_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name=op.f("fk_exercise_content_feedback_exercise_id_exercises"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exercise_content_feedback")),
    )
    op.create_index(
        "ix_exercise_content_feedback_user_id", "exercise_content_feedback", ["user_id"]
    )
    op.create_index(
        "ix_exercise_content_feedback_exercise_id", "exercise_content_feedback", ["exercise_id"]
    )
    op.create_index(
        "ix_exercise_content_feedback_exercise_created",
        "exercise_content_feedback",
        ["exercise_id", "created_at"],
    )

    op.create_table(
        "alerts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("alert_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), server_default="warning", nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        *_id_and_timestamps(),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name=op.f("ck_alerts_severity"),
        ),
        sa.CheckConstraint("status IN ('open', 'dismissed')", name=op.f("ck_alerts_status")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_alerts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])
    op.create_index("ix_alerts_user_created", "alerts", ["user_id", "created_at"])

    op.drop_constraint(
        op.f("ck_calendar_reschedule_drafts_strategy"),
        "calendar_reschedule_drafts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_calendar_reschedule_drafts_strategy"),
        "calendar_reschedule_drafts",
        "strategy IN ('shift', 'merge', 'skip', 'compression', 'substitution')",
    )
    op.drop_constraint(op.f("ck_image_assets_purpose"), "image_assets", type_="check")
    op.create_check_constraint(
        op.f("ck_image_assets_purpose"),
        "image_assets",
        "purpose IN ('chat_attachment', 'nutrition_entry', 'body_progress', 'training_plan')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_image_assets_purpose"), "image_assets", type_="check")
    op.create_check_constraint(
        op.f("ck_image_assets_purpose"),
        "image_assets",
        "purpose IN ('chat_attachment', 'nutrition_entry', 'body_progress')",
    )
    op.drop_constraint(
        op.f("ck_calendar_reschedule_drafts_strategy"),
        "calendar_reschedule_drafts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_calendar_reschedule_drafts_strategy"),
        "calendar_reschedule_drafts",
        "strategy IN ('shift', 'merge', 'skip')",
    )
    op.drop_table("alerts")
    op.drop_table("exercise_content_feedback")
    op.drop_table("recipes")
    op.drop_index("ix_foods_barcode", table_name="foods")
    op.drop_column("foods", "barcode")
