"""add workout set void fields

Revision ID: 9c3f7a1e5d82
Revises: 6e1d4b9a2c75
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c3f7a1e5d82"
down_revision: str | Sequence[str] | None = "6e1d4b9a2c75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workout_sets", sa.Column("voided_at", sa.DateTime(timezone=True)))
    op.add_column("workout_sets", sa.Column("void_reason", sa.String(length=1000)))


def downgrade() -> None:
    op.drop_column("workout_sets", "void_reason")
    op.drop_column("workout_sets", "voided_at")
