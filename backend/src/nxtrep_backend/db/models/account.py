from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from nxtrep_backend.db.models.goals import UserConstraint, UserGoal


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProfileSex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNSPECIFIED = "unspecified"


class ExperienceLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="user_status",
        ),
        Index("uq_users_username_ci", func.lower(text("username")), unique=True),
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=UserStatus.ACTIVE.value,
        server_default=UserStatus.ACTIVE.value,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    password_setup_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    credential: Mapped[Credential | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    profile: Mapped[Profile | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    refresh_sessions: Mapped[list[RefreshSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    goals: Mapped[list[UserGoal]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    constraints: Mapped[UserConstraint | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Credential(TimestampMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint(
            "failed_login_attempts >= 0",
            name="failed_login_attempts_non_negative",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash: Mapped[str | None] = mapped_column(String(255))
    setup_token_hash: Mapped[str | None] = mapped_column(String(255), unique=True)
    setup_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="credential")


class Profile(TimestampMixin, Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "sex IN ('male', 'female', 'other', 'unspecified')",
            name="profile_sex",
        ),
        CheckConstraint(
            "experience_level IS NULL OR experience_level IN "
            "('beginner', 'intermediate', 'advanced')",
            name="experience_level",
        ),
        CheckConstraint("height_cm > 0 AND height_cm <= 300", name="height_cm_range"),
        CheckConstraint(
            "weekly_training_days >= 0 AND weekly_training_days <= 7",
            name="weekly_training_days_range",
        ),
        CheckConstraint(
            "session_duration_minutes > 0 AND session_duration_minutes <= 1440",
            name="session_duration_minutes_range",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(80))
    sex: Mapped[str] = mapped_column(
        String(11),
        nullable=False,
        default=ProfileSex.UNSPECIFIED.value,
        server_default=ProfileSex.UNSPECIFIED.value,
    )
    birth_date: Mapped[date | None] = mapped_column(Date)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    experience_level: Mapped[str | None] = mapped_column(String(12))
    weekly_training_days: Mapped[int | None] = mapped_column(SmallInteger)
    session_duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Shanghai",
        server_default="Asia/Shanghai",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    user: Mapped[User] = relationship(back_populates="profile")


class RefreshSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    device_name: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="refresh_sessions")


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint(
            "unit_system IN ('metric', 'imperial')",
            name="unit_system",
        ),
        CheckConstraint(
            "privacy_mode IN ('private', 'summary')",
            name="privacy_mode",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_system: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="metric",
        server_default="metric",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Shanghai",
        server_default="Asia/Shanghai",
    )
    privacy_mode: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="private",
        server_default="private",
    )
    share_anonymous_analytics: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    user: Mapped[User] = relationship(back_populates="settings")
