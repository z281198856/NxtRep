from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class BodyProgressPhoto(IdMixin, TimestampMixin, Base):
    __tablename__ = "body_progress_photos"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_body_progress_photos_user_captured", "user_id", "captured_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    image_asset_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("image_assets.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    view: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    notes: Mapped[str | None] = mapped_column(String(2000))
    assessment: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
