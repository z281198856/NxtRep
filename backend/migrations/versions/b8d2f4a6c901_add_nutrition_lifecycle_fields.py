"""add nutrition lifecycle fields

Revision ID: b8d2f4a6c901
Revises: 9c3f7a1e5d82
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d2f4a6c901"
down_revision: str | Sequence[str] | None = "9c3f7a1e5d82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("nutrition_entries", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_table(
        "flexible_meals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False, server_default="自由餐"),
        sa.Column("notes", sa.String(length=1000)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_flexible_meals_version_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_flexible_meals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flexible_meals")),
        sa.UniqueConstraint("user_id", "scheduled_date", name="uq_flexible_meals_user_date"),
    )
    op.create_index("ix_flexible_meals_user_date", "flexible_meals", ["user_id", "scheduled_date"])
    op.create_index(op.f("ix_flexible_meals_user_id"), "flexible_meals", ["user_id"])


def downgrade() -> None:
    op.drop_table("flexible_meals")
    op.drop_column("nutrition_entries", "deleted_at")
    op.drop_column("foods", "deleted_at")
