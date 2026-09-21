"""allow cancelled confirmations

Revision ID: d4a7e2c8f103
Revises: b8d2f4a6c901
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a7e2c8f103"
down_revision: str | Sequence[str] | None = "b8d2f4a6c901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_confirmations_status"), "confirmations", type_="check")
    op.create_check_constraint(
        op.f("ck_confirmations_status"),
        "confirmations",
        "status IN ('pending', 'succeeded', 'rejected', 'cancelled', 'failed', 'expired')",
    )


def downgrade() -> None:
    op.execute("UPDATE confirmations SET status = 'rejected' WHERE status = 'cancelled'")
    op.drop_constraint(op.f("ck_confirmations_status"), "confirmations", type_="check")
    op.create_check_constraint(
        op.f("ck_confirmations_status"),
        "confirmations",
        "status IN ('pending', 'succeeded', 'rejected', 'failed', 'expired')",
    )
