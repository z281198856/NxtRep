# ruff: noqa: E501
"""seed USDA food catalog

Revision ID: 7b9d2e4f6a81
Revises: fc07f60845fc
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7b9d2e4f6a81"
down_revision: str | Sequence[str] | None = "fc07f60845fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOOD_IDS = (
    "40000000-0000-4000-8000-000000000001",
    "40000000-0000-4000-8000-000000000002",
    "40000000-0000-4000-8000-000000000003",
)

VERSION_IDS = (
    "41000000-0000-4000-8000-000000000001",
    "41000000-0000-4000-8000-000000000002",
    "41000000-0000-4000-8000-000000000003",
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO foods
            (
                id,
                owner_user_id,
                name,
                brand,
                region,
                state
            )
        VALUES
            (
                '40000000-0000-4000-8000-000000000001',
                NULL,
                '熟白米饭',
                NULL,
                'CN',
                'cooked'
            ),
            (
                '40000000-0000-4000-8000-000000000002',
                NULL,
                '熟鸡胸肉',
                NULL,
                'CN',
                'cooked'
            ),
            (
                '40000000-0000-4000-8000-000000000003',
                NULL,
                '熟西兰花',
                NULL,
                'CN',
                'cooked'
            )
        ON CONFLICT (id) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO food_versions
            (
                id,
                food_id,
                version,
                basis_amount_g,
                kcal,
                protein_g,
                carbs_g,
                fat_g,
                source,
                confidence
            )
        VALUES
            (
                '41000000-0000-4000-8000-000000000001',
                '40000000-0000-4000-8000-000000000001',
                1,
                100.000, 130.00, 2.690, 28.170, 0.280,
                'usda_fdc_168878',
                'high'
            ),
            (
                '41000000-0000-4000-8000-000000000002',
                '40000000-0000-4000-8000-000000000002',
                1,
                100.000, 165.00, 31.020, 0.000, 3.570,
                'usda_fdc_171477',
                'high'
            ),
            (
                '41000000-0000-4000-8000-000000000003',
                '40000000-0000-4000-8000-000000000003',
                1,
                100.000, 35.00, 2.380, 7.180, 0.410,
                'usda_fdc_169967',
                'high'
            )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    version_ids = ", ".join(f"'{value}'" for value in VERSION_IDS)
    food_ids = ", ".join(f"'{value}'" for value in FOOD_IDS)

    op.execute(f"DELETE FROM food_versions WHERE id IN ({version_ids})")
    op.execute(f"DELETE FROM foods WHERE id IN ({food_ids})")
