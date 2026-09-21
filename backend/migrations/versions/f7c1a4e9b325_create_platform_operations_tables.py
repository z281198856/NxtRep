"""create platform operations tables

Revision ID: f7c1a4e9b325
Revises: e5b8c3d9a214
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7c1a4e9b325"
down_revision: str | Sequence[str] | None = "e5b8c3d9a214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_and_timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("categories", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("frequency", sa.String(20), server_default="important_only", nullable=False),
        sa.Column("quiet_hours", postgresql.JSONB()),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _user_fk("notification_settings"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_settings")),
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        *_id_and_timestamps(),
        _user_fk("notifications"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_table(
        "push_devices",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(160), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_last_four", sa.String(4), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_id_and_timestamps(),
        _user_fk("push_devices"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_devices")),
        sa.UniqueConstraint("user_id", "device_id", name="uq_push_devices_user_device"),
    )
    op.create_table(
        "sync_resources",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_id_and_timestamps(),
        _user_fk("sync_resources"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_resources")),
        sa.UniqueConstraint(
            "user_id", "resource_type", "resource_key", name="uq_sync_resources_identity"
        ),
    )
    op.create_table(
        "sync_changes",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB()),
        *_id_and_timestamps(),
        _user_fk("sync_changes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_changes")),
        sa.UniqueConstraint("sequence", name=op.f("uq_sync_changes_sequence")),
    )
    op.create_index("ix_sync_changes_user_sequence", "sync_changes", ["user_id", "sequence"])
    op.create_table(
        "sync_conflicts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_key", sa.String(160), nullable=False),
        sa.Column("client_payload", postgresql.JSONB(), nullable=False),
        sa.Column("server_payload", postgresql.JSONB(), nullable=False),
        sa.Column("client_version", sa.Integer(), nullable=False),
        sa.Column("server_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(20)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_id_and_timestamps(),
        sa.CheckConstraint("status IN ('open', 'resolved')", name=op.f("ck_sync_conflicts_status")),
        _user_fk("sync_conflicts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_conflicts")),
    )
    op.create_table(
        "export_jobs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        *_id_and_timestamps(),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')", name=op.f("ck_export_jobs_status")
        ),
        _user_fk("export_jobs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_jobs")),
    )
    op.create_table(
        "deletion_drafts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("preview", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovery_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_id_and_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'expired')", name=op.f("ck_deletion_drafts_status")
        ),
        _user_fk("deletion_drafts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_drafts")),
    )
    op.create_table(
        "audit_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        *_id_and_timestamps(),
        _user_fk("audit_events"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_user_created", "audit_events", ["user_id", "created_at"])
    op.create_table(
        "generated_reports",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("missing_data", postgresql.JSONB(), nullable=False),
        sa.Column("recommendations", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_id_and_timestamps(),
        sa.CheckConstraint(
            "report_type IN ('weekly', 'monthly', 'phase')", name=op.f("ck_generated_reports_type")
        ),
        _user_fk("generated_reports"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_reports")),
        sa.UniqueConstraint(
            "user_id",
            "report_type",
            "period_start",
            "period_end",
            name="uq_generated_reports_period",
        ),
    )
    op.create_index(
        "ix_generated_reports_user_period", "generated_reports", ["user_id", "period_start"]
    )


def downgrade() -> None:
    for table in (
        "generated_reports",
        "audit_events",
        "deletion_drafts",
        "export_jobs",
        "sync_conflicts",
        "sync_changes",
        "sync_resources",
        "push_devices",
        "notifications",
        "notification_settings",
    ):
        op.drop_table(table)
