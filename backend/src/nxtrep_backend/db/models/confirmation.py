from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class Confirmation(IdMixin, TimestampMixin, Base):
    """Durable command awaiting explicit approval or rejection."""

    __tablename__ = "confirmations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'rejected', 'failed', 'expired')", name="status"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_confirmations_user_status", "user_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    impact: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
