from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreWorkoutCheck(StrictModel):
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    pain: list[dict] = Field(default_factory=list)
    available_minutes: int | None = Field(default=None, ge=1, le=300)


class WorkoutPreCheckUpdateRequest(PreWorkoutCheck):
    expected_version: int = Field(ge=1)


class WorkoutCreateRequest(StrictModel):
    calendar_event_id: UUID | None = None
    plan_day_id: UUID | None = None
    started_at: datetime
    pre_check: PreWorkoutCheck | None = None

    @field_validator("started_at")
    @classmethod
    def require_started_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("started_at must include a timezone offset")
        return value


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

    @field_validator("completed_at")
    @classmethod
    def require_completed_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must include a timezone offset")
        return value


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


class WorkoutExerciseAddRequest(StrictModel):
    exercise_id: UUID
    target_sets: int = Field(default=3, ge=1, le=20)
    rep_min: int = Field(default=8, ge=1, le=100)
    rep_max: int = Field(default=12, ge=1, le=100)
    target_load_kg: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    target_rir: int | None = Field(default=None, ge=0, le=10)
    rest_seconds: int | None = Field(default=None, ge=0, le=1800)
    expected_workout_version: int = Field(ge=1)


class WorkoutExerciseSkipRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_workout_version: int = Field(ge=1)


class WorkoutSetVoidRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)


class WorkoutPauseRequest(StrictModel):
    paused_at: datetime | None = None
    expected_version: int = Field(ge=1)

    @field_validator("paused_at")
    @classmethod
    def require_paused_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("paused_at must include a timezone offset")
        return value


class WorkoutResumeRequest(StrictModel):
    resumed_at: datetime | None = None
    expected_version: int = Field(ge=1)

    @field_validator("resumed_at")
    @classmethod
    def require_resumed_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("resumed_at must include a timezone offset")
        return value


class WorkoutAbandonRequest(StrictModel):
    ended_at: datetime
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)

    @field_validator("ended_at")
    @classmethod
    def require_abandon_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ended_at must include a timezone offset")
        return value


class WorkoutFinishRequest(StrictModel):
    ended_at: datetime
    overall_difficulty: int | None = Field(default=None, ge=1, le=5)
    fatigue: int | None = Field(default=None, ge=1, le=5)
    pain: list[dict] = Field(default_factory=list)
    interruption_reason: str | None = Field(default=None, max_length=1000)
    expected_version: int = Field(ge=1)

    @field_validator("ended_at")
    @classmethod
    def require_ended_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ended_at must include a timezone offset")
        return value


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
    voided_at: datetime | None = None
    void_reason: str | None = None
    version: int


class WorkoutExerciseResponse(BaseModel):
    id: UUID
    exercise_id: UUID | None
    name_snapshot: str
    target_snapshot: dict
    skipped: bool = False
    skip_reason: str | None = None
    sets: list[WorkoutSetResponse]


class WorkoutRestTimerResponse(BaseModel):
    workout_exercise_id: UUID
    set_id: UUID
    duration_seconds: int
    started_at: datetime
    ends_at: datetime
    remaining_seconds: int


class WorkoutResponse(BaseModel):
    id: UUID
    status: str
    started_at: datetime
    ended_at: datetime | None
    paused_at: datetime | None = None
    total_paused_seconds: int = 0
    elapsed_seconds: int = 0
    rest_timer: WorkoutRestTimerResponse | None = None
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


class WorkoutSummaryResponse(WorkoutFinishResponse):
    status: str
    started_at: datetime
    ended_at: datetime | None


class ProgressionDraftResponse(BaseModel):
    id: UUID
    suggestions: list[dict]
    version: int


class WorkoutRevisionResponse(BaseModel):
    id: UUID
    set_id: UUID
    old_values: dict
    new_values: dict
    reason: str
    created_at: datetime
