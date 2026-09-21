from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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


class Workout(IdMixin, TimestampMixin, Base):
    __tablename__ = "workouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'paused', 'completed', 'interrupted')",
            name="status",
        ),
        CheckConstraint("total_paused_seconds >= 0", name="total_paused_seconds_non_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_workouts_user_started_at", "user_id", "started_at"),
        Index(
            "uq_workouts_one_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('in_progress', 'paused')"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calendar_event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("calendar_events.id", ondelete="SET NULL")
    )
    plan_day_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_paused_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    pre_check: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    overall_difficulty: Mapped[int | None] = mapped_column(Integer)
    fatigue: Mapped[int | None] = mapped_column(Integer)
    pain: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    interruption_reason: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class WorkoutExercise(IdMixin, TimestampMixin, Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        UniqueConstraint("workout_id", "order_no", name="uq_workout_exercises_workout_order"),
    )

    workout_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("exercises.id", ondelete="SET NULL"), index=True
    )
    original_exercise_id: Mapped[UUID | None] = mapped_column(Uuid)
    name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    target_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    replacement_history: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkoutSet(IdMixin, TimestampMixin, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("set_index >= 1", name="set_index_positive"),
        CheckConstraint("weight_kg >= 0", name="weight_non_negative"),
        CheckConstraint("reps >= 0", name="reps_non_negative"),
        CheckConstraint("rir IS NULL OR rir BETWEEN 0 AND 10", name="rir_range"),
        CheckConstraint("rpe IS NULL OR rpe BETWEEN 1 AND 10", name="rpe_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("workout_id", "client_generated_id", name="uq_workout_sets_client_id"),
        UniqueConstraint("workout_exercise_id", "set_index", name="uq_workout_sets_exercise_index"),
    )

    workout_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workout_exercise_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workout_exercises.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_generated_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    set_index: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    rir: Mapped[int | None] = mapped_column(Integer)
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class WorkoutSetRevision(IdMixin, TimestampMixin, Base):
    __tablename__ = "workout_set_revisions"

    set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workout_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)


class ProgressionDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "progression_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('editing', 'submitted')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workout_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    suggestions: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="editing")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class PersonalRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "personal_records"
    __table_args__ = (Index("ix_personal_records_user_occurred", "user_id", "occurred_at"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("exercises.id", ondelete="SET NULL"), index=True
    )
    exercise_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workout_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )
    set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workout_sets.id", ondelete="CASCADE"), nullable=False
    )
