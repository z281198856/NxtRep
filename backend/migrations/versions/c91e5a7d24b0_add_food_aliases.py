"""add food aliases

Revision ID: c91e5a7d24b0
Revises: e82f4a1c6d39
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91e5a7d24b0"
down_revision: str | Sequence[str] | None = "e82f4a1c6d39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "food_aliases",
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
            name=op.f("fk_food_aliases_food_id_foods"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_aliases")),
        sa.UniqueConstraint(
            "food_id",
            "alias",
            name=op.f("uq_food_aliases_food_alias"),
        ),
    )
    op.create_index(
        op.f("ix_food_aliases_food_id"),
        "food_aliases",
        ["food_id"],
    )
    op.create_index("ix_food_aliases_alias", "food_aliases", ["alias"])
    op.execute(
        """
        INSERT INTO food_aliases (id, food_id, alias)
        VALUES
          ('42000000-0000-4000-8000-000000000001',
           '40000000-0000-4000-8000-000000000001', '米饭'),
          ('42000000-0000-4000-8000-000000000002',
           '40000000-0000-4000-8000-000000000001', '白米饭'),
          ('42000000-0000-4000-8000-000000000003',
           '40000000-0000-4000-8000-000000000002', '鸡胸'),
          ('42000000-0000-4000-8000-000000000004',
           '40000000-0000-4000-8000-000000000002', '鸡胸肉'),
          ('42000000-0000-4000-8000-000000000005',
           '40000000-0000-4000-8000-000000000003', '青花菜'),
          ('42000000-0000-4000-8000-000000000006',
           '40000000-0000-4000-8000-000000000003', 'broccoli')
        ON CONFLICT (food_id, alias) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("food_aliases")
