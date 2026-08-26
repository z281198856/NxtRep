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
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class BodyMeasurement(IdMixin, TimestampMixin, Base):
    __tablename__ = "body_measurements"
    __table_args__ = (
        CheckConstraint(
            "weight_kg IS NOT NULL OR waist_cm IS NOT NULL OR "
            "neck_cm IS NOT NULL OR hip_cm IS NOT NULL OR body_fat_percent IS NOT NULL",
            name="at_least_one_measurement",
        ),
        CheckConstraint(
            "body_fat_percent IS NULL OR body_fat_percent BETWEEN 1 AND 70",
            name="body_fat_percent_range",
        ),
        CheckConstraint(
            "(weight_kg IS NULL OR weight_kg > 0) AND "
            "(waist_cm IS NULL OR waist_cm > 0) AND "
            "(neck_cm IS NULL OR neck_cm > 0) AND "
            "(hip_cm IS NULL OR hip_cm > 0)",
            name="measurements_positive",
        ),
        CheckConstraint(
            "(body_fat_percent IS NULL AND body_fat_method IS NULL) OR "
            "(body_fat_percent IS NOT NULL AND body_fat_method IS NOT NULL)",
            name="body_fat_method_pair",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_body_measurements_user_measured", "user_id", "measured_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    neck_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    hip_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    body_fat_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    body_fat_method: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    conditions: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class BodyMeasurementRevision(IdMixin, TimestampMixin, Base):
    __tablename__ = "body_measurement_revisions"

    measurement_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("body_measurements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)


class BodyFatEstimate(IdMixin, TimestampMixin, Base):
    __tablename__ = "body_fat_estimates"
    __table_args__ = (Index("ix_body_fat_estimates_user_calculated", "user_id", "calculated_at"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    value_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    range_min_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    range_max_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
