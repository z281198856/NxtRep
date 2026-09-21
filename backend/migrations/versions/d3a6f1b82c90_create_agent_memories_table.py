"""create agent memories table

Revision ID: d3a6f1b82c90
Revises: 7b9d2e4f6a81
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a6f1b82c90"
down_revision: str | Sequence[str] | None = "7b9d2e4f6a81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("content", sa.String(length=2000), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('long_term_goal', 'equipment', 'schedule', 'allergy', "
            "'dietary_preference', 'exercise_limit', "
            "'communication_preference', 'other')",
            name=op.f("ck_agent_memories_category"),
        ),
        sa.CheckConstraint(
            "length(btrim(content)) > 0",
            name=op.f("ck_agent_memories_content_not_blank"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_agent_memories_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_memories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_memories")),
    )
    op.create_index(
        op.f("ix_agent_memories_user_id"),
        "agent_memories",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_memories_user_category",
        "agent_memories",
        ["user_id", "category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_memories_user_category", table_name="agent_memories")
    op.drop_index(op.f("ix_agent_memories_user_id"), table_name="agent_memories")
    op.drop_table("agent_memories")
