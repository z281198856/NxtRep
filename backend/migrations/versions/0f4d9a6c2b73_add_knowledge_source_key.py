"""add knowledge source key

Revision ID: 0f4d9a6c2b73
Revises: f6a2b8c4d901
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f4d9a6c2b73"
down_revision: str | Sequence[str] | None = "f6a2b8c4d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_sources",
        sa.Column("source_key", sa.String(length=120), nullable=True),
    )
    op.execute(
        """
        UPDATE knowledge_sources
        SET source_key = 'legacy-' || replace(id::text, '-', '')
        WHERE source_key IS NULL
        """
    )
    op.alter_column(
        "knowledge_sources",
        "source_key",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_knowledge_sources_source_key_not_blank"),
        "knowledge_sources",
        "length(btrim(source_key)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_knowledge_sources_source_key_lowercase"),
        "knowledge_sources",
        "source_key = lower(source_key)",
    )
    op.create_unique_constraint(
        op.f("uq_knowledge_sources_source_key"),
        "knowledge_sources",
        ["source_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_knowledge_sources_source_key"),
        "knowledge_sources",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_knowledge_sources_source_key_not_blank"),
        "knowledge_sources",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_knowledge_sources_source_key_lowercase"),
        "knowledge_sources",
        type_="check",
    )
    op.drop_column("knowledge_sources", "source_key")
