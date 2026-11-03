"""Add bounded Agent task state to the existing conversation.

Revision ID: da6e91c7b240
Revises: c5d6e7f8a901
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "da6e91c7b240"
down_revision = "c5d6e7f8a901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column(
            "task_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_conversations", "task_state")
