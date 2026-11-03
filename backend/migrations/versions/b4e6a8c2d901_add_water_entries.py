"""Add water intake records independent of meal nutrition."""

import sqlalchemy as sa
from alembic import op

revision = "b4e6a8c2d901"
down_revision = "a9d6e4c1b832"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "water_entries",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_ml", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount_ml BETWEEN 1 AND 5000", name="amount_ml_range"),
    )
    op.create_index("ix_water_entries_user_consumed", "water_entries", ["user_id", "consumed_at"])


def downgrade() -> None:
    op.drop_table("water_entries")
