from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class Exercise(IdMixin, TimestampMixin, Base):
    """官方动作或用户创建的自定义动作。"""

    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(name_zh)) > 0",
            name="name_zh_not_blank",
        ),
        CheckConstraint(
            "length(btrim(equipment)) > 0",
            name="equipment_not_blank",
        ),
        CheckConstraint(
            "version >= 1",
            name="version_positive",
        ),
    )

    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name_zh: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    movement_pattern: Mapped[str | None] = mapped_column(
        String(40),
    )

    equipment: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )

    difficulty: Mapped[str | None] = mapped_column(
        String(20),
    )

    instructions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    breathing: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    common_errors: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    safety_notes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )

    notes: Mapped[str | None] = mapped_column(
        String(1000),
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    @property
    def is_custom(self) -> bool:
        return self.owner_user_id is not None


class ExerciseMuscle(TimestampMixin, Base):
    """动作与主要、次要肌群之间的关系。"""

    __tablename__ = "exercise_muscles"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(muscle_code)) > 0",
            name="muscle_code_not_blank",
        ),
        CheckConstraint(
            "role IN ('primary', 'secondary')",
            name="role",
        ),
        Index(
            "ix_exercise_muscles_muscle_code_role",
            "muscle_code",
            "role",
        ),
    )

    exercise_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        primary_key=True,
    )

    muscle_code: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
    )

    role: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )


class ExerciseAlias(IdMixin, TimestampMixin, Base):
    """用于搜索动作的常见名称和简称。"""

    __tablename__ = "exercise_aliases"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(alias)) > 0",
            name="alias_not_blank",
        ),
        CheckConstraint(
            "length(btrim(normalized_alias)) > 0",
            name="normalized_alias_not_blank",
        ),
        UniqueConstraint(
            "exercise_id",
            "normalized_alias",
            name="uq_exercise_aliases_exercise_normalized",
        ),
    )

    exercise_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    alias: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    normalized_alias: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )


class ExerciseSubstitution(IdMixin, TimestampMixin, Base):
    """一个动作可以替换成另一个动作及其原因。"""

    __tablename__ = "exercise_substitutions"
    __table_args__ = (
        CheckConstraint(
            "source_exercise_id != target_exercise_id",
            name="different_exercises",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0",
            name="reason_not_blank",
        ),
        CheckConstraint(
            "priority >= 1",
            name="priority_positive",
        ),
        UniqueConstraint(
            "source_exercise_id",
            "target_exercise_id",
            name="uq_exercise_substitutions_source_target",
        ),
        Index(
            "ix_exercise_substitutions_source_priority",
            "source_exercise_id",
            "priority",
        ),
        Index(
            "ix_exercise_substitutions_target",
            "target_exercise_id",
        ),
    )

    source_exercise_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )

    target_exercise_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )


class ExerciseMedia(IdMixin, TimestampMixin, Base):
    """动作循环动效或静态图片的存储元数据。"""

    __tablename__ = "exercise_media"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('animation', 'image')",
            name="media_type",
        ),
        CheckConstraint(
            "length(btrim(storage_key)) > 0",
            name="storage_key_not_blank",
        ),
        CheckConstraint(
            "sort_order >= 1",
            name="sort_order_positive",
        ),
        UniqueConstraint(
            "storage_key",
            name="uq_exercise_media_storage_key",
        ),
        Index(
            "ix_exercise_media_exercise_sort_order",
            "exercise_id",
            "sort_order",
        ),
    )

    exercise_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )

    media_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    view_angle: Mapped[str | None] = mapped_column(
        String(40),
    )

    alt_text: Mapped[str | None] = mapped_column(
        String(500),
    )

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )


class ExerciseContentFeedback(IdMixin, TimestampMixin, Base):
    """用户对动作讲解、分类或媒体内容提交的纠错反馈。"""

    __tablename__ = "exercise_content_feedback"
    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('instruction', 'classification', 'media', 'safety', 'other')",
            name="feedback_type",
        ),
        CheckConstraint("status IN ('open', 'resolved', 'dismissed')", name="status"),
        Index("ix_exercise_content_feedback_exercise_created", "exercise_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open"
    )
