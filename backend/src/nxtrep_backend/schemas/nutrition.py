from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FoodCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    barcode: str | None = Field(
        default=None, min_length=4, max_length=64, pattern=r"^[0-9A-Za-z-]+$"
    )
    basis_amount_g: Decimal = Field(gt=0, max_digits=8, decimal_places=3)
    kcal: Decimal = Field(ge=0, max_digits=9, decimal_places=2)
    protein_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    carbs_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    fat_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)


class CustomFoodDraftRequest(FoodCreateRequest):
    source: Literal["user_provided", "model_estimated", "web_reference"] = "model_estimated"
    confidence: Literal["low", "medium", "high"] = "low"
    notes: str = Field(min_length=1, max_length=2000)

    @field_validator("name")
    @classmethod
    def require_food_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class FoodResponse(BaseModel):
    id: UUID
    food_version_id: UUID
    name: str
    brand: str | None = None
    barcode: str | None = None
    state: str | None = None
    basis_amount_g: Decimal
    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    source: str
    confidence: str


class FoodUpdateRequest(FoodCreateRequest):
    expected_version: int = Field(ge=1)


class CustomFoodPatchRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    barcode: str | None = Field(
        default=None, min_length=4, max_length=64, pattern=r"^[0-9A-Za-z-]+$"
    )
    basis_amount_g: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=3)
    kcal: Decimal | None = Field(default=None, ge=0, max_digits=9, decimal_places=2)
    protein_g: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=3)
    carbs_g: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=3)
    fat_g: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=3)
    source: (
        Literal["user_provided", "model_estimated", "web_reference", "user_confirmed"] | None
    ) = None
    confidence: Literal["low", "medium", "high"] | None = None
    notes: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_explicit_change(self) -> "CustomFoodPatchRequest":
        business = self.model_fields_set - {"source", "confidence", "notes"}
        if not business:
            raise ValueError("at least one food field must change")
        for field in business - {"brand", "barcode"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        if self.name is not None and not self.name.strip():
            raise ValueError("name must not be blank")
        return self


class FrequentFoodResponse(FoodResponse):
    use_count: int = Field(ge=1)


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
    estimate_assumptions: str | None = Field(default=None, max_length=2000)

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

    @field_validator("eaten_at")
    @classmethod
    def require_eaten_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eaten_at must include a timezone offset")
        return value


class NutritionEntryCopyRequest(StrictModel):
    expected_version: int = Field(ge=1)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    eaten_at: datetime

    @field_validator("eaten_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eaten_at must include a timezone offset")
        return value


class NutritionEstimateCorrection(StrictModel):
    """Nutrient totals for the resulting eaten portion, never per 100 grams."""

    kcal: Decimal = Field(ge=0, max_digits=10, decimal_places=3)
    protein_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    carbs_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    fat_g: Decimal = Field(ge=0, max_digits=8, decimal_places=3)
    assumptions: str = Field(min_length=1, max_length=2000)

    @field_validator("assumptions")
    @classmethod
    def require_basis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请说明本次重估采用的食材、做法或份量依据。")
        return value.strip()


class NutritionPortionChange(StrictModel):
    item_index: int = Field(ge=0)
    amount_g: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=3)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    nutrition_estimate: NutritionEstimateCorrection | None = None
    replacement: NutritionItemInput | None = None

    @model_validator(mode="after")
    def require_change(self) -> "NutritionPortionChange":
        if self.replacement is not None:
            if any(
                value is not None for value in (self.amount_g, self.name, self.nutrition_estimate)
            ):
                raise ValueError("替换食物请只提供replacement中的新食物、份量和营养依据。")
        elif self.amount_g is None and self.nutrition_estimate is None and self.name is None:
            raise ValueError("请指定份量、名称或有依据的营养重估。")
        return self


class NutritionPendingEntryRevisionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    changes: list[NutritionPortionChange] = Field(default_factory=list, max_length=50)
    additions: list[NutritionItemInput] = Field(default_factory=list, max_length=50)
    remove_item_indices: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list, max_length=50
    )
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def unique_items(self) -> "NutritionPendingEntryRevisionRequest":
        indices = [change.item_index for change in self.changes]
        if len(indices) != len(set(indices)):
            raise ValueError("Each item can be changed only once")
        if len(set(self.remove_item_indices)) != len(self.remove_item_indices):
            raise ValueError("同一食物不能重复移除。")
        if set(indices) & set(self.remove_item_indices):
            raise ValueError("同一食物不能同时修改和移除。")
        if not (self.changes or self.additions or self.remove_item_indices):
            raise ValueError("请指定要修改、新增或移除的食物。")
        return self


class NutritionSavedPortionChange(StrictModel):
    item_index: int = Field(ge=0)
    amount_g: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=3)
    nutrition_estimate: NutritionEstimateCorrection | None = None
    replacement: NutritionItemInput | None = None

    @model_validator(mode="after")
    def require_change(self) -> "NutritionSavedPortionChange":
        if self.replacement is not None:
            if self.amount_g is not None or self.nutrition_estimate is not None:
                raise ValueError(
                    "替换食物请在replacement中提供新食物和份量，不同时更正原食物营养。"
                )
        elif self.amount_g is None and self.nutrition_estimate is None:
            raise ValueError("请指定份量、有依据的营养重估或替换食物。")
        return self


class NutritionSavedEntryRevisionRequest(StrictModel):
    expected_version: int = Field(ge=1)
    changes: list[NutritionSavedPortionChange] = Field(default_factory=list, max_length=50)
    remove_item_indices: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list, max_length=50
    )
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_items(self):
        indices = [change.item_index for change in self.changes]
        if len(indices) != len(set(indices)):
            raise ValueError("同一食物不能重复更正份量。")
        removals = self.remove_item_indices
        if len(removals) != len(set(removals)):
            raise ValueError("同一食物不能重复移除。")
        if set(indices) & set(removals):
            raise ValueError("同一食物不能同时更正份量和移除。")
        if not indices and not removals:
            raise ValueError("请指定需要更正份量或移除的食物。")
        return self


class NutritionDateChangeEntry(StrictModel):
    entry_id: UUID
    expected_version: int = Field(ge=1)


class NutritionDateChangeRequest(StrictModel):
    source_date: date
    target_date: date
    entries: list[NutritionDateChangeEntry] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_move(self):
        if self.source_date == self.target_date:
            raise ValueError("原日期和目标日期相同，无需更正。")
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("同一餐食不能重复移动。")
        return self


class NutritionEntryUpdateRequest(StrictModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None
    eaten_at: datetime | None = None
    items: list[NutritionItemInput] | None = Field(default=None, min_length=1)
    is_flexible_meal: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)

    @field_validator("eaten_at")
    @classmethod
    def require_updated_eaten_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("eaten_at must include a timezone offset")
        return value


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


class NutritionEntryDeleteRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(default="用户请求删除饮食记录", min_length=1, max_length=1000)


class NutritionTextDraftRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"]
    eaten_at: datetime
    is_flexible_meal: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("eaten_at")
    @classmethod
    def require_draft_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eaten_at must include a timezone offset")
        return value


class NutritionEntryDraftUpdateRequest(StrictModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None
    eaten_at: datetime | None = None
    items: list[NutritionItemInput] | None = Field(default=None, min_length=1)
    is_flexible_meal: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)

    @field_validator("eaten_at")
    @classmethod
    def require_updated_draft_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("eaten_at must include a timezone offset")
        return value


class NutritionEntryDraftResponse(BaseModel):
    id: UUID
    original_text: str | None
    meal_type: str
    eaten_at: datetime
    items: list[dict]
    totals: NutritionTotals
    missing_items: list[str]
    questions: list[str]
    is_flexible_meal: bool
    notes: str | None
    status: str
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
    water_ml: int = 0
    recorded_meals: list[str] = Field(default_factory=list)
    date: date
    target: dict | None
    consumed: NutritionTotals
    remaining: dict | None
    record_completeness: Decimal


class WeeklyNutritionSummaryResponse(BaseModel):
    start_date: date
    end_date: date
    daily_average: NutritionTotals
    total_entries: int
    recorded_days: int
    flexible_meals: int
    record_completeness: Decimal


class NutritionAdviceRequest(StrictModel):
    food_name: str = Field(min_length=1, max_length=160)
    amount_g: Decimal | None = Field(default=None, gt=0)
    on_date: date


class NutritionAdviceResponse(BaseModel):
    food_name: str
    recommendation: str
    remaining: dict | None
    cautions: list[str] = Field(default_factory=list)


class NutritionTargetVersionResponse(BaseModel):
    id: UUID
    target_id: UUID
    effective_from: date
    values: dict
    version: int
    status: str


class DynamicNutritionTargetDraftRequest(StrictModel):
    effective_from: date
    desired_direction: Literal["decrease", "maintain", "increase"] = "maintain"


class RecipeCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    servings: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    items: list[NutritionItemInput] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class RecipeUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    servings: Decimal | None = Field(default=None, gt=0, max_digits=8, decimal_places=2)
    items: list[NutritionItemInput] | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_changes(self) -> "RecipeUpdateRequest":
        supplied = self.model_fields_set - {"expected_version"}
        if not supplied:
            raise ValueError("At least one recipe field must be provided")
        for name in supplied & {"name", "servings", "items"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class RecipeResponse(BaseModel):
    id: UUID
    name: str
    servings: Decimal
    items: list[dict]
    totals: NutritionTotals
    notes: str | None
    version: int


class FlexibleMealCreateRequest(StrictModel):
    scheduled_date: date
    label: str = Field(default="自由餐", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class FlexibleMealUpdateRequest(StrictModel):
    scheduled_date: date | None = None
    label: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    expected_version: int = Field(ge=1)


class FlexibleMealResponse(BaseModel):
    id: UUID
    scheduled_date: date
    label: str
    notes: str | None
    version: int


class FoodImageCandidate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    estimated_amount_g: Decimal = Field(gt=0)
    amount_min_g: Decimal = Field(gt=0)
    amount_max_g: Decimal = Field(gt=0)
    confidence: Literal["low", "medium", "high"]
    visual_evidence: str | None = Field(default=None, max_length=500)
    portion_basis: str | None = Field(default=None, max_length=500)
    portion_confidence: Literal["low", "medium", "high"] = "low"

    @model_validator(mode="after")
    def validate_amount_range(self) -> "FoodImageCandidate":
        if not (self.amount_min_g <= self.estimated_amount_g <= self.amount_max_g):
            raise ValueError("estimated amount must be within amount range")
        return self


class NutritionImageEstimateRequest(StrictModel):
    image_asset_id: UUID
    meal_type: Literal[
        "breakfast",
        "lunch",
        "dinner",
        "snack",
        "other",
    ]
    eaten_at: datetime
    notes: str | None = Field(default=None, max_length=2000)
    reviewed_foods: list[FoodImageCandidate] | None = Field(
        default=None, min_length=1, max_length=20
    )

    @field_validator("eaten_at")
    @classmethod
    def require_eaten_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eaten_at must include a timezone offset")
        return value


class FoodImageRecognitionResult(StrictModel):
    foods: list[FoodImageCandidate] = Field(
        default_factory=list,
        max_length=20,
    )
    assumptions: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        max_length=10,
    )


class FoodCatalogMatchResult(StrictModel):
    detected: FoodImageCandidate
    status: Literal[
        "matched",
        "needs_confirmation",
        "not_found",
    ]
    selected: FoodResponse | None = None
    alternatives: list[FoodResponse] = Field(
        default_factory=list,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_match_state(self) -> "FoodCatalogMatchResult":
        if self.status == "matched" and self.selected is None:
            raise ValueError("matched result requires selected food")

        if self.status == "needs_confirmation" and not self.alternatives:
            raise ValueError("needs_confirmation requires alternatives")

        if self.status == "not_found" and (self.selected is not None or self.alternatives):
            raise ValueError("not_found cannot contain catalog foods")

        return self


class NutritionEstimateRange(StrictModel):
    minimum: NutritionTotals
    estimated: NutritionTotals
    maximum: NutritionTotals

    @model_validator(mode="after")
    def validate_ranges(self) -> "NutritionEstimateRange":
        for name in (
            "kcal",
            "protein_g",
            "carbs_g",
            "fat_g",
        ):
            if not (
                getattr(self.minimum, name)
                <= getattr(self.estimated, name)
                <= getattr(self.maximum, name)
            ):
                raise ValueError(f"{name} estimate must be within range")

        return self


class FoodNutritionDraftItem(StrictModel):
    match: FoodCatalogMatchResult
    nutrition: NutritionEstimateRange | None = None
    source: str | None = Field(default=None, max_length=40)
    confidence: str | None = Field(default=None, max_length=20)
    requires_confirmation: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=10)


class NutritionDraftCalculation(StrictModel):
    items: list[FoodNutritionDraftItem]
    totals: NutritionEstimateRange
    is_complete: bool
    requires_confirmation: bool = False


class NutritionImageAnalysisResult(StrictModel):
    recognition: FoodImageRecognitionResult
    calculation: NutritionDraftCalculation


class NutritionImageDraftResponse(NutritionImageEstimateRequest):
    recognition: FoodImageRecognitionResult
    calculation: NutritionDraftCalculation


class FoodNutritionFallbackEstimate(StrictModel):
    food_name: str = Field(min_length=1, max_length=160)
    basis_amount_g: Decimal = Field(
        default=Decimal("100"),
        gt=0,
    )
    nutrition_per_100g: NutritionEstimateRange
    assumptions: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        max_length=10,
    )
    source: Literal["model_estimated"] = "model_estimated"
    confidence: Literal["low"] = "low"
    requires_confirmation: Literal[True] = True

    @field_validator("basis_amount_g")
    @classmethod
    def require_100g_basis(
        cls,
        value: Decimal,
    ) -> Decimal:
        if value != Decimal("100"):
            raise ValueError("fallback nutrition basis must be 100 grams")
        return value


class FoodNutritionFallbackResult(StrictModel):
    estimates: list[FoodNutritionFallbackEstimate] = Field(
        min_length=1,
        max_length=20,
    )
