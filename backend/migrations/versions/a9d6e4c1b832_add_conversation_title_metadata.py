"""Track automatic conversation titles without overwriting user names."""

import sqlalchemy as sa
from alembic import op

revision = "a9d6e4c1b832"
down_revision = "f8c5d3b0a721"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("title_source", sa.String(16), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("title_through_sequence", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_conversations", "title_through_sequence")
    op.drop_column("agent_conversations", "title_source")
