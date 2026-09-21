from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class ImageAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "image_assets"

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('chat_attachment', 'nutrition_entry', 'body_progress', 'training_plan')",
            name="purpose",
        ),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="content_type",
        ),
        CheckConstraint(
            "content_length > 0",
            name="content_length_positive",
        ),
        CheckConstraint(
            "status IN ('pending_upload', 'uploaded', 'ready', 'failed', 'deleted')",
            name="status",
        ),
        CheckConstraint(
            "length(trim(object_key)) > 0",
            name="object_key_not_blank",
        ),
        UniqueConstraint(
            "object_key",
            name="uq_image_assets_object_key",
        ),
        Index(
            "ix_image_assets_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_image_assets_status_upload_expiry",
            "status",
            "upload_expires_at",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    content_length: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending_upload",
        server_default="pending_upload",
    )
    upload_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    etag: Mapped[str | None] = mapped_column(
        String(128),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(1000),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
