from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from nxtrep_backend.db.models.account import User


class GoalType(StrEnum):
    MUSCLE_GAIN = "muscle_gain"
    FAT_LOSS_RETAIN = "fat_loss_retain"
    RECOMPOSITION = "recomposition"
    MAINTAIN = "maintain"
    STRENGTH = "strength"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class UserGoal(IdMixin, TimestampMixin, Base):
    """A versioned user goal; old rows are retained instead of overwritten."""

    __tablename__ = "user_goals"
    __table_args__ = (
        CheckConstraint(
            "goal_type IN "
            "('muscle_gain', 'fat_loss_retain', 'recomposition', 'maintain', 'strength')",
            name="goal_type",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="goal_status",
        ),
        CheckConstraint(
            "target_weight_kg IS NULL OR (target_weight_kg > 0 AND target_weight_kg <= 500)",
            name="target_weight_kg_range",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("user_id", "version", name="uq_user_goals_user_id_version"),
        Index(
            "uq_user_goals_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=GoalStatus.ACTIVE.value,
        server_default=GoalStatus.ACTIVE.value,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    user: Mapped[User] = relationship(back_populates="goals")


class UserConstraint(TimestampMixin, Base):
    """The user's current training, injury, allergy, and dietary constraints."""

    __tablename__ = "user_constraints"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    equipment: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    preferred_exercise_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    disliked_exercise_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    pain_or_injuries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    allergies: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    dietary_preferences: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    user: Mapped[User] = relationship(back_populates="constraints")
