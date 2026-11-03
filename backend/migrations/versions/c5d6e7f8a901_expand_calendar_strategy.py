"""Allow existing compression and substitution strategies to be saved.

Revision ID: c5d6e7f8a901
Revises: b3c4d5e6f7a8
"""

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a901"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "calendar_reschedule_drafts",
        "strategy",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=False,
    )


def downgrade():
    # PostgreSQL refuses narrowing if longer values exist, preserving the data.
    op.alter_column(
        "calendar_reschedule_drafts",
        "strategy",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=False,
    )
