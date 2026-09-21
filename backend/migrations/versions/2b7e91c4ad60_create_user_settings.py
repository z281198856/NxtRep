"""create user settings

Revision ID: 2b7e91c4ad60
Revises: 0f4d9a6c2b73
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b7e91c4ad60"
down_revision: str | Sequence[str] | None = "0f4d9a6c2b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "unit_system",
            sa.String(length=8),
            server_default="metric",
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Asia/Shanghai",
            nullable=False,
        ),
        sa.Column(
            "privacy_mode",
            sa.String(length=8),
            server_default="private",
            nullable=False,
        ),
        sa.Column(
            "share_anonymous_analytics",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "unit_system IN ('metric', 'imperial')",
            name=op.f("ck_user_settings_unit_system"),
        ),
        sa.CheckConstraint(
            "privacy_mode IN ('private', 'summary')",
            name=op.f("ck_user_settings_privacy_mode"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_user_settings_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.execute(
        """
        INSERT INTO user_settings (user_id, timezone)
        SELECT users.id, COALESCE(profiles.timezone, 'Asia/Shanghai')
        FROM users
        LEFT JOIN profiles ON profiles.user_id = users.id
        """
    )


def downgrade() -> None:
    op.drop_table("user_settings")
