from datetime import datetime
from enum import StrEnum
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


class IdempotencyStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class IdempotencyRecord(IdMixin, TimestampMixin, Base):
    """Stores the stable result of an idempotent mutation."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(operation)) > 0",
            name="operation_not_blank",
        ),
        CheckConstraint(
            "length(btrim(request_hash)) > 0",
            name="request_hash_not_blank",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed')",
            name="status",
        ),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 200 AND 599",
            name="response_status_range",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_idempotency_records_user_key",
        ),
        Index(
            "ix_idempotency_records_expires_at",
            "expires_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=IdempotencyStatus.PROCESSING.value,
        server_default=text("'processing'"),
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
