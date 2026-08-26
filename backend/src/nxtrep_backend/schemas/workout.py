from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreWorkoutCheck(StrictModel):
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    pain: list[dict] = Field(default_factory=list)
    available_minutes: int | None = Field(default=None, ge=1, le=300)


class WorkoutCreateRequest(StrictModel):
    calendar_event_id: UUID | None = None
    plan_day_id: UUID | None = None
    started_at: datetime
    pre_check: PreWorkoutCheck | None = None


class WorkoutSetCreateRequest(StrictModel):
    client_generated_id: UUID
    workout_exercise_id: UUID
    set_index: int = Field(ge=1)
    weight_kg: Decimal = Field(ge=0, max_digits=7, decimal_places=3)
    reps: int = Field(ge=0, le=1000)
    rir: int | None = Field(default=None, ge=0, le=10)
    rpe: Decimal | None = Field(default=None, ge=1, le=10, decimal_places=1)
    tags: list[Literal["warmup", "working", "failure", "drop"]] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)
    completed_at: datetime


class WorkoutSetUpdateRequest(StrictModel):
    weight_kg: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    reps: int | None = Field(default=None, ge=0, le=1000)
    rir: int | None = Field(default=None, ge=0, le=10)
    rpe: Decimal | None = Field(default=None, ge=1, le=10, decimal_places=1)
    tags: list[Literal["warmup", "working", "failure", "drop"]] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)


class WorkoutExerciseReplaceRequest(StrictModel):
    replacement_exercise_id: UUID
    reason: str = Field(min_length=1, max_length=1000)
    expected_workout_version: int = Field(ge=1)


class WorkoutFinishRequest(StrictModel):
    ended_at: datetime
    overall_difficulty: int | None = Field(default=None, ge=1, le=5)
    fatigue: int | None = Field(default=None, ge=1, le=5)
    pain: list[dict] = Field(default_factory=list)
    interruption_reason: str | None = Field(default=None, max_length=1000)
    expected_version: int = Field(ge=1)


class ProgressionDraftCreateRequest(StrictModel):
    exercise_ids: list[UUID] | None = None


class ExpectedVersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class WorkoutSetResponse(BaseModel):
    id: UUID
    set_index: int
    weight_kg: Decimal
    reps: int
    rir: int | None
    rpe: Decimal | None
    tags: list[str]
    notes: str | None
    completed_at: datetime
    version: int


class WorkoutExerciseResponse(BaseModel):
    id: UUID
    exercise_id: UUID | None
    name_snapshot: str
    target_snapshot: dict
    sets: list[WorkoutSetResponse]


class WorkoutResponse(BaseModel):
    id: UUID
    status: str
    started_at: datetime
    ended_at: datetime | None
    version: int
    pre_check: dict
    exercises: list[WorkoutExerciseResponse]
    overall_difficulty: int | None = None
    fatigue: int | None = None
    pain: list[dict] = Field(default_factory=list)
    interruption_reason: str | None = None


class WorkoutHistoryItem(BaseModel):
    id: UUID
    date: date
    status: str
    duration_seconds: int | None
    completed_sets: int
    total_volume_kg: Decimal
    pr_count: int


class WorkoutHistoryResponse(BaseModel):
    list: list[WorkoutHistoryItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class WorkoutFinishResponse(BaseModel):
    workout_id: UUID
    duration_seconds: int
    completed_sets: int
    total_volume_kg: Decimal
    prs: list[dict]
    pain_flags: list[dict]
    plan_adherence: Decimal


class ProgressionDraftResponse(BaseModel):
    id: UUID
    suggestions: list[dict]
    version: int
