from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FoodCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    basis_amount_g: Decimal = Field(gt=0, max_digits=8, decimal_places=3)
    kcal: Decimal = Field(ge=0, max_digits=9, decimal_places=2)
    protein_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    carbs_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    fat_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)


class FoodResponse(BaseModel):
    id: UUID
    food_version_id: UUID
    name: str
    brand: str | None = None
    state: str | None = None
    basis_amount_g: Decimal
    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    source: str
    confidence: str


class FoodSearchResponse(BaseModel):
    list: list[FoodResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class NutritionItemInput(StrictModel):
    food_version_id: UUID | None = None
    amount_g: Decimal = Field(gt=0, max_digits=8, decimal_places=3)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    basis_amount_g: Decimal | None = Field(default=None, gt=0)
    kcal: Decimal | None = Field(default=None, ge=0)
    protein_g: Decimal | None = Field(default=None, ge=0)
    carbs_g: Decimal | None = Field(default=None, ge=0)
    fat_g: Decimal | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=40)
    confidence: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validate_source(self) -> "NutritionItemInput":
        if self.food_version_id is None:
            required = (
                self.name,
                self.basis_amount_g,
                self.kcal,
                self.protein_g,
                self.carbs_g,
                self.fat_g,
                self.source,
                self.confidence,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "custom estimates require name, basis, nutrients, source and confidence"
                )
        return self


class NutritionEntryCreateRequest(StrictModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    eaten_at: datetime
    items: list[NutritionItemInput] = Field(min_length=1)
    is_flexible_meal: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class NutritionEntryUpdateRequest(StrictModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None
    eaten_at: datetime | None = None
    items: list[NutritionItemInput] | None = Field(default=None, min_length=1)
    is_flexible_meal: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)


class NutritionTotals(BaseModel):
    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal


class NutritionEntryResponse(BaseModel):
    id: UUID
    meal_type: str
    eaten_at: datetime
    items: list[dict]
    totals: NutritionTotals
    is_flexible_meal: bool
    notes: str | None
    version: int


class NutritionTargetDraftRequest(StrictModel):
    effective_from: date
    kcal_min: Decimal = Field(ge=0)
    kcal_max: Decimal = Field(ge=0)
    protein_min_g: Decimal = Field(ge=0)
    protein_max_g: Decimal = Field(ge=0)
    carbs_min_g: Decimal = Field(ge=0)
    carbs_max_g: Decimal = Field(ge=0)
    fat_min_g: Decimal = Field(ge=0)
    fat_max_g: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "NutritionTargetDraftRequest":
        for nutrient in ("kcal", "protein", "carbs", "fat"):
            suffix = "" if nutrient == "kcal" else "_g"
            if getattr(self, f"{nutrient}_min{suffix}") > getattr(self, f"{nutrient}_max{suffix}"):
                raise ValueError(f"{nutrient} minimum must not exceed maximum")
        return self


class NutritionTargetDraftResponse(NutritionTargetDraftRequest):
    id: UUID
    status: str
    version: int


class ExpectedVersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class DailyNutritionSummaryResponse(BaseModel):
    date: date
    target: dict | None
    consumed: NutritionTotals
    remaining: dict | None
    record_completeness: Decimal
