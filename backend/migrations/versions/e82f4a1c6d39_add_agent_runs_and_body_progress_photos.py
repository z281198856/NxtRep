"""add agent runs and body progress photos

Revision ID: e82f4a1c6d39
Revises: a4c9e1d73f20
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e82f4a1c6d39"
down_revision: str | Sequence[str] | None = "a4c9e1d73f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("title", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "agent_conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "agent_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="running", nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
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
            "status IN ('running', 'succeeded', 'failed', 'cancel_requested', 'cancelled')",
            name=op.f("ck_agent_runs_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_agent_runs_version_positive")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_agent_runs_conversation_id_agent_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_runs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(op.f("ix_agent_runs_user_id"), "agent_runs", ["user_id"])
    op.create_index(
        "ix_agent_runs_user_created",
        "agent_runs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_agent_runs_conversation_created",
        "agent_runs",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "body_progress_photos",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("image_asset_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("view", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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
            "version >= 1",
            name=op.f("ck_body_progress_photos_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["image_asset_id"],
            ["image_assets.id"],
            name=op.f("fk_body_progress_photos_image_asset_id_image_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_body_progress_photos_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_body_progress_photos")),
        sa.UniqueConstraint(
            "image_asset_id",
            name=op.f("uq_body_progress_photos_image_asset_id"),
        ),
    )
    op.create_index(
        op.f("ix_body_progress_photos_user_id"),
        "body_progress_photos",
        ["user_id"],
    )
    op.create_index(
        "ix_body_progress_photos_user_captured",
        "body_progress_photos",
        ["user_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_table("body_progress_photos")
    op.drop_table("agent_runs")
    op.drop_column("agent_conversations", "deleted_at")
    op.drop_column("agent_conversations", "title")
