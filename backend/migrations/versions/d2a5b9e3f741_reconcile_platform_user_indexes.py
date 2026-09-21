"""reconcile platform user indexes

Revision ID: d2a5b9e3f741
Revises: c1f4a8d2e630
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2a5b9e3f741"
down_revision: str | Sequence[str] | None = "c1f4a8d2e630"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "audit_events",
    "deletion_drafts",
    "export_jobs",
    "generated_reports",
    "notifications",
    "push_devices",
    "sync_changes",
    "sync_conflicts",
    "sync_resources",
)


def upgrade() -> None:
    for table_name in _TABLES:
        op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"])


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
