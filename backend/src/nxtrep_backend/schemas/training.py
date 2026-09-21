from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanExerciseInput(StrictModel):
    exercise_id: UUID
    order_no: int = Field(ge=1)
    target_sets: int = Field(ge=1, le=20)
    rep_min: int = Field(ge=1, le=100)
    rep_max: int = Field(ge=1, le=100)
    target_load_kg: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    target_rir: int | None = Field(default=None, ge=0, le=10)
    rest_seconds: int | None = Field(default=None, ge=0, le=1800)

    @model_validator(mode="after")
    def validate_rep_range(self) -> "PlanExerciseInput":
        if self.rep_min > self.rep_max:
            raise ValueError("rep_min must not exceed rep_max")
        return self


class PlanDayInput(StrictModel):
    day_index: int = Field(ge=1, le=7)
    name: str = Field(min_length=1, max_length=120)
    estimated_minutes: int = Field(ge=1, le=300)
    exercises: list[PlanExerciseInput]

    @model_validator(mode="after")
    def validate_exercise_order(self) -> "PlanDayInput":
        order = [item.order_no for item in self.exercises]
        if len(order) != len(set(order)):
            raise ValueError("exercise order_no values must be unique within a day")
        return self


class PlanDraftCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    weekly_frequency: int = Field(ge=1, le=7)
    days: list[PlanDayInput] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_days(self) -> "PlanDraftCreateRequest":
        indexes = [day.day_index for day in self.days]
        if len(indexes) != len(set(indexes)):
            raise ValueError("day_index values must be unique")
        if self.weekly_frequency != len(self.days):
            raise ValueError("weekly_frequency must equal the number of days")
        return self


class PlanDraftFromTemplateRequest(StrictModel):
    template_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PlanDraftParseTextRequest(StrictModel):
    text: str = Field(min_length=1, max_length=10_000)
    template_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PlanDraftParseImageRequest(StrictModel):
    image_asset_id: UUID
    template_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PlanDraftGenerateRequest(StrictModel):
    goal_type: str | None = Field(default=None, max_length=40)
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    equipment: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PlanDraftUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    weekly_frequency: int | None = Field(default=None, ge=1, le=7)
    days: list[PlanDayInput] | None = Field(default=None, min_length=1, max_length=7)
    expected_version: int = Field(ge=1)


class ExpectedVersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class TrainingTemplateResponse(BaseModel):
    id: UUID
    name: str
    goal_types: list[str]
    days_per_week: int
    duration_minutes: int


class TrainingTemplateDetailResponse(TrainingTemplateResponse):
    equipment: list[str]
    days: list[dict]


class PlanDraftResponse(BaseModel):
    id: UUID
    name: str
    status: str
    version: int
    weekly_frequency: int
    days: list[dict]
    validation_errors: list[dict] = Field(default_factory=list)
    validation_warnings: list[dict] = Field(default_factory=list)


class PlanValidationResponse(BaseModel):
    valid: bool
    errors: list[dict]
    warnings: list[dict]
    estimated_weekly_minutes: int


class ActivePlanResponse(BaseModel):
    id: UUID
    plan_id: UUID
    name: str
    version: int
    weekly_frequency: int
    days: list[dict]
    activated_at: datetime


class PlanVersionItemResponse(ActivePlanResponse):
    status: str


class PlanVersionListResponse(BaseModel):
    list: list[PlanVersionItemResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class PlanRevisionDraftRequest(StrictModel):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PlanArchiveDraftRequest(StrictModel):
    expected_version: int = Field(ge=1)


class CalendarEventResponse(BaseModel):
    id: UUID
    scheduled_date: date
    status: str
    plan_day_id: UUID | None
    title: str
    estimated_minutes: int
    actual_workout_id: UUID | None


class CalendarEventDetailResponse(CalendarEventResponse):
    plan_version_id: UUID | None
    content_snapshot: dict | None


class CalendarEventCreateRequest(StrictModel):
    scheduled_date: date
    title: str = Field(min_length=1, max_length=120)
    estimated_minutes: int = Field(ge=1, le=300)
    exercises: list[PlanExerciseInput] = Field(default_factory=list, max_length=50)


class RescheduleDraftCreateRequest(StrictModel):
    missed_event_id: UUID
    strategy: Literal["shift", "merge", "skip"]
    target_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_target(self) -> "RescheduleDraftCreateRequest":
        if self.strategy in {"shift", "merge"} and self.target_date is None:
            raise ValueError("target_date is required for shift and merge")
        return self


class RescheduleDraftResponse(BaseModel):
    id: UUID
    strategy: str
    before_events: list[dict]
    after_events: list[dict]
    duration_change_minutes: int
    volume_change_percent: Decimal
    warnings: list[str]
    version: int


class CompressionDraftCreateRequest(StrictModel):
    event_id: UUID
    target_minutes: Literal[15, 30, 45]
    reason: str | None = Field(default=None, max_length=1000)


class SubstitutionDraftCreateRequest(StrictModel):
    event_id: UUID
    exercise_id: UUID
    replacement_exercise_id: UUID
    reason: str = Field(min_length=1, max_length=1000)
