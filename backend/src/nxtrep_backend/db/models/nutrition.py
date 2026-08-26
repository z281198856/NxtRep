from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin


class Food(IdMixin, TimestampMixin, Base):
    __tablename__ = "foods"
    __table_args__ = (Index("ix_foods_name_brand", "name", "brand"),)

    owner_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(40), index=True)
    state: Mapped[str | None] = mapped_column(String(30), index=True)


class FoodVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "food_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("basis_amount_g > 0", name="basis_amount_positive"),
        CheckConstraint(
            "kcal >= 0 AND protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0",
            name="nutrients_non_negative",
        ),
        UniqueConstraint("food_id", "version", name="uq_food_versions_food_version"),
    )

    food_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("foods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    basis_amount_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    kcal: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False)
    protein_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    fat_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)


class NutritionEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_entries"
    __table_args__ = (
        CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'other')",
            name="meal_type",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_nutrition_entries_user_eaten", "user_id", "eaten_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    items: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_flexible_meal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class NutritionEntryRevision(IdMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_entry_revisions"

    entry_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("nutrition_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    new_values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)


class NutritionTargetDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_target_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('editing', 'submitted')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    kcal_min: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False)
    kcal_max: Mapped[Decimal] = mapped_column(Numeric(9, 2), nullable=False)
    protein_min_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    protein_max_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    carbs_min_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    carbs_max_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    fat_min_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    fat_max_g: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="editing")
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class NutritionTargetVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_target_versions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'superseded')", name="status"),
        UniqueConstraint(
            "target_id", "version", name="uq_nutrition_target_versions_target_version"
        ),
        Index(
            "uq_nutrition_target_versions_one_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, default=uuid4, index=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_draft_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("nutrition_target_drafts.id", ondelete="SET NULL")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
