from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class AgentConversation(IdMixin, TimestampMixin, Base):
    """A user-scoped durable Agent conversation and its rolling summary."""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint(
            "summary_through_sequence >= 0",
            name="summary_through_sequence_non_negative",
        ),
        CheckConstraint("next_sequence >= 1", name="next_sequence_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_agent_conversations_user_last_message", "user_id", "last_message_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    summary: Mapped[str | None] = mapped_column(Text)
    summary_through_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    next_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(String(120))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )


class AgentMessage(IdMixin, TimestampMixin, Base):
    """One ordered user or assistant message in an Agent conversation."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_agent_messages_conversation_sequence",
        ),
        Index("ix_agent_messages_conversation_sequence", "conversation_id", "sequence"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    image_asset_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
