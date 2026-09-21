"""create nutrition entry drafts

Revision ID: a9d3e6f1c427
Revises: f7c1a4e9b325
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9d3e6f1c427"
down_revision: str | Sequence[str] | None = "f7c1a4e9b325"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nutrition_entry_drafts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("original_text", sa.String(4000)),
        sa.Column("meal_type", sa.String(20), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("totals", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("missing_items", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("questions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("is_flexible_meal", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("notes", sa.String(2000)),
        sa.Column("status", sa.String(20), server_default="editing", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('editing', 'submitted')", name=op.f("ck_nutrition_entry_drafts_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_nutrition_entry_drafts_version_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_nutrition_entry_drafts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nutrition_entry_drafts")),
    )
    op.create_index(
        "ix_nutrition_entry_drafts_user_status", "nutrition_entry_drafts", ["user_id", "status"]
    )
    op.create_index(
        op.f("ix_nutrition_entry_drafts_user_id"), "nutrition_entry_drafts", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("nutrition_entry_drafts")
