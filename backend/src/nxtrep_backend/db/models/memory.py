from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class AgentMemory(IdMixin, TimestampMixin, Base):
    """An active or soft-deleted long-term user fact."""

    __tablename__ = "agent_memories"
    __table_args__ = (
        CheckConstraint(
            "category IN ('long_term_goal', 'equipment', 'schedule', 'allergy', "
            "'dietary_preference', 'exercise_limit', "
            "'communication_preference', 'other')",
            name="category",
        ),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_agent_memories_user_category", "user_id", "category"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
