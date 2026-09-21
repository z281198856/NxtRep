from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SearchKeyword = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
    ),
]

ExerciseCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]


class ExerciseListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: SearchKeyword | None = None
    equipment: ExerciseCode | None = None
    muscle: ExerciseCode | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ExerciseListItemResponse(BaseModel):
    id: UUID
    name_zh: str
    aliases: list[str]
    equipment: str
    primary_muscles: list[str]
    is_custom: bool


class ExerciseListResponse(BaseModel):
    list: list[ExerciseListItemResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_more: bool


class ExerciseSubstitutionResponse(BaseModel):
    id: UUID
    name_zh: str
    equipment: str
    reason: str


class ExerciseDetailResponse(BaseModel):
    id: UUID
    name_zh: str
    aliases: list[str]
    movement_pattern: str | None
    equipment: str
    difficulty: str | None
    primary_muscles: list[str]
    secondary_muscles: list[str]
    instructions: list[str]
    breathing: list[str]
    common_errors: list[str]
    safety_notes: list[str]
    substitutions: list[ExerciseSubstitutionResponse]
    notes: str | None
    version: int = Field(ge=1)
    is_custom: bool


class ExerciseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_zh: SearchKeyword
    equipment: ExerciseCode
    primary_muscles: list[ExerciseCode] = Field(
        min_length=1,
        max_length=50,
    )
    secondary_muscles: list[ExerciseCode] = Field(
        default_factory=list,
        max_length=50,
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
    )

    @field_validator(
        "primary_muscles",
        "secondary_muscles",
    )
    @classmethod
    def reject_duplicate_muscles(
        cls,
        value: list[str],
    ) -> list[str]:
        normalized = [item.casefold() for item in value]

        if len(normalized) != len(set(normalized)):
            raise ValueError("Muscle list must not contain duplicates")

        return value

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value

    @model_validator(mode="after")
    def reject_overlapping_muscles(self) -> Self:
        overlap = set(self.primary_muscles).intersection(self.secondary_muscles)

        if overlap:
            raise ValueError("A muscle cannot be both primary and secondary")

        return self


class ExerciseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_zh: SearchKeyword | None = None
    equipment: ExerciseCode | None = None
    primary_muscles: list[ExerciseCode] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    secondary_muscles: list[ExerciseCode] | None = Field(
        default=None,
        max_length=50,
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
    )
    expected_version: int = Field(ge=1)

    @field_validator(
        "primary_muscles",
        "secondary_muscles",
    )
    @classmethod
    def reject_duplicate_muscles(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None

        normalized = [item.casefold() for item in value]

        if len(normalized) != len(set(normalized)):
            raise ValueError("Muscle list must not contain duplicates")

        return value

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        update_fields = {
            "name_zh",
            "equipment",
            "primary_muscles",
            "secondary_muscles",
            "notes",
        }

        supplied_fields = self.model_fields_set.intersection(update_fields)

        if not supplied_fields:
            raise ValueError("At least one exercise field must be provided")

        non_nullable_fields = {
            "name_zh",
            "equipment",
            "primary_muscles",
            "secondary_muscles",
        }

        for field_name in supplied_fields.intersection(non_nullable_fields):
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")

        if self.primary_muscles is not None and self.secondary_muscles is not None:
            overlap = set(self.primary_muscles).intersection(self.secondary_muscles)

            if overlap:
                raise ValueError("A muscle cannot be both primary and secondary")

        return self


class ExerciseHistorySetResponse(BaseModel):
    set_index: int
    weight_kg: Decimal
    reps: int
    rir: int | None
    rpe: Decimal | None
    completed_at: datetime


class ExerciseHistoryItemResponse(BaseModel):
    workout_id: UUID
    started_at: datetime
    status: str
    name_snapshot: str
    sets: list[ExerciseHistorySetResponse]


class ExerciseHistoryResponse(BaseModel):
    exercise_id: UUID
    history: list[ExerciseHistoryItemResponse]


class ExerciseClassificationDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ExerciseClassificationDraftResponse(BaseModel):
    exercise_id: UUID
    expected_version: int
    suggested_movement_pattern: str | None
    suggested_difficulty: str | None
    suggested_primary_muscles: list[str]
    suggested_secondary_muscles: list[str]
    confidence: Decimal
    requires_review: bool = True


class ExerciseMediaResponse(BaseModel):
    id: UUID
    exercise_id: UUID
    media_type: str
    view_angle: str | None
    alt_text: str | None
    sort_order: int
    download_url: str
    expires_at: datetime


class ExerciseContentFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_type: Literal["instruction", "classification", "media", "safety", "other"]
    message: str = Field(min_length=1, max_length=2000)
    context: dict = Field(default_factory=dict)


class ExerciseContentFeedbackResponse(BaseModel):
    id: UUID
    exercise_id: UUID
    feedback_type: str
    message: str
    context: dict
    status: str
    created_at: datetime
