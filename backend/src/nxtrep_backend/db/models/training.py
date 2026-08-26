from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class TrainingTemplate(IdMixin, TimestampMixin, Base):
    """Official plan template including its immutable day/exercise snapshot."""

    __tablename__ = "training_templates"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("days_per_week BETWEEN 1 AND 7", name="days_per_week_range"),
        CheckConstraint("duration_minutes BETWEEN 1 AND 300", name="duration_minutes_range"),
        CheckConstraint("jsonb_typeof(goal_types) = 'array'", name="goal_types_array"),
        CheckConstraint("jsonb_typeof(equipment) = 'array'", name="equipment_array"),
        UniqueConstraint("name", name="uq_training_templates_name"),
        Index("ix_training_templates_active_days", "is_active", "days_per_week"),
        Index("ix_training_templates_goal_types_gin", "goal_types", postgresql_using="gin"),
        Index("ix_training_templates_equipment_gin", "equipment", postgresql_using="gin"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    equipment: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    days: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class TrainingPlanDraft(IdMixin, TimestampMixin, Base):
    """Editable plan that cannot become active without confirmation."""

    __tablename__ = "training_plan_drafts"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("weekly_frequency BETWEEN 1 AND 7", name="weekly_frequency_range"),
        CheckConstraint("status IN ('editing', 'submitted')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_training_plan_drafts_user_status", "user_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    weekly_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="editing", server_default="editing"
    )
    validation_errors: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    validation_warnings: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class TrainingPlanVersion(IdMixin, TimestampMixin, Base):
    """Immutable activated plan version; plan_id groups its history."""

    __tablename__ = "training_plan_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('active', 'superseded')", name="status"),
        UniqueConstraint("plan_id", "version", name="uq_training_plan_versions_plan_version"),
        Index(
            "uq_training_plan_versions_one_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    plan_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, default=uuid4, index=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_draft_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("training_plan_drafts.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    weekly_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CalendarEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint("status IN ('planned', 'completed', 'missed', 'skipped')", name="status"),
        CheckConstraint(
            "estimated_minutes BETWEEN 1 AND 300", name="estimated_minutes_range"
        ),
        Index("ix_calendar_events_user_date", "user_id", "scheduled_date"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned", server_default="planned"
    )
    plan_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("training_plan_versions.id", ondelete="SET NULL")
    )
    plan_day_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    actual_workout_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "workouts.id",
            name="fk_calendar_events_actual_workout_id_workouts",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )


class CalendarRescheduleDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "calendar_reschedule_drafts"
    __table_args__ = (
        CheckConstraint("strategy IN ('shift', 'merge', 'skip')", name="strategy"),
        CheckConstraint("status IN ('editing', 'submitted')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    missed_event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False
    )
    strategy: Mapped[str] = mapped_column(String(10), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(1000))
    before_events: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    after_events: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    duration_change_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume_change_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("0")
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="editing", server_default="editing"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
