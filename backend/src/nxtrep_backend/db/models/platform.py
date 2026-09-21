from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class NotificationSetting(TimestampMixin, Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    categories: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default="important_only", server_default="important_only"
    )
    quiet_hours: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class AppNotification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushDevice(IdMixin, TimestampMixin, Base):
    __tablename__ = "push_devices"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_push_devices_user_device"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncResource(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_resources"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "resource_type", "resource_key", name="uq_sync_resources_identity"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class SyncChange(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_changes"
    __table_args__ = (Index("ix_sync_changes_user_sequence", "user_id", "sequence"),)

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(10), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)


class SyncConflict(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_conflicts"
    __table_args__ = (CheckConstraint("status IN ('open', 'resolved')", name="status"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(160), nullable=False)
    client_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    server_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    client_version: Mapped[int] = mapped_column(Integer, nullable=False)
    server_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open"
    )
    resolution: Mapped[str | None] = mapped_column(String(20))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class DeletionDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "deletion_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'expired')", name="status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="account")
    preview: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recovery_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AuditEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_user_created", "user_id", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class GeneratedReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "generated_reports"
    __table_args__ = (
        CheckConstraint("report_type IN ('weekly', 'monthly', 'phase')", name="type"),
        UniqueConstraint(
            "user_id",
            "report_type",
            "period_start",
            "period_end",
            name="uq_generated_reports_period",
        ),
        Index("ix_generated_reports_user_period", "user_id", "period_start"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    missing_data: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AppAlert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity"),
        CheckConstraint("status IN ('open', 'dismissed')", name="status"),
        Index("ix_alerts_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning", server_default="warning"
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open"
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
