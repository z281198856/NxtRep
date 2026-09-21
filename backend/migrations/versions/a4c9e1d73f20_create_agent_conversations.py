"""create agent conversations and messages

Revision ID: a4c9e1d73f20
Revises: d3a6f1b82c90
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4c9e1d73f20"
down_revision: str | Sequence[str] | None = "d3a6f1b82c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "summary_through_sequence",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("next_sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
            "status IN ('active', 'archived')",
            name=op.f("ck_agent_conversations_status"),
        ),
        sa.CheckConstraint(
            "summary_through_sequence >= 0",
            name=op.f("ck_agent_conversations_summary_through_sequence_non_negative"),
        ),
        sa.CheckConstraint(
            "next_sequence >= 1",
            name=op.f("ck_agent_conversations_next_sequence_positive"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_agent_conversations_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_conversations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    op.create_index(
        op.f("ix_agent_conversations_user_id"),
        "agent_conversations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_conversations_user_last_message",
        "agent_conversations",
        ["user_id", "last_message_at"],
        unique=False,
    )

    op.create_table(
        "agent_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "image_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            "length(btrim(content)) > 0",
            name=op.f("ck_agent_messages_content_not_blank"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name=op.f("ck_agent_messages_role"),
        ),
        sa.CheckConstraint(
            "sequence >= 1",
            name=op.f("ck_agent_messages_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_agent_messages_conversation_id_agent_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_agent_messages_conversation_sequence",
        ),
    )
    op.create_index(
        "ix_agent_messages_conversation_sequence",
        "agent_messages",
        ["conversation_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_messages_conversation_sequence",
        table_name="agent_messages",
    )
    op.drop_table("agent_messages")
    op.drop_index(
        "ix_agent_conversations_user_last_message",
        table_name="agent_conversations",
    )
    op.drop_index(
        op.f("ix_agent_conversations_user_id"),
        table_name="agent_conversations",
    )
    op.drop_table("agent_conversations")
