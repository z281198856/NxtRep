"""add body measurement soft delete

Revision ID: e5b8c3d9a214
Revises: d4a7e2c8f103
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b8c3d9a214"
down_revision: str | Sequence[str] | None = "d4a7e2c8f103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("body_measurements", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("body_measurements", "deleted_at")
