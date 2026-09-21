from datetime import date
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

GoalTypeValue = Literal[
    "muscle_gain",
    "fat_loss_retain",
    "recomposition",
    "maintain",
    "strength",
]
GoalStatusValue = Literal["active", "superseded"]
InjuryKindValue = Literal[
    "current_pain",
    "past_injury",
    "movement_limitation",
]

EquipmentCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class PainOrInjuryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InjuryKindValue
    body_part: ShortText
    severity: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value


class GoalsAndConstraintsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_type: GoalTypeValue
    target_date: date | None = None
    target_weight_kg: Decimal | None = Field(
        default=None,
        gt=0,
        le=500,
        max_digits=6,
        decimal_places=3,
    )
    equipment: list[EquipmentCode] = Field(max_length=50)
    preferred_exercises: list[UUID] = Field(default_factory=list, max_length=100)
    disliked_exercises: list[UUID] = Field(default_factory=list, max_length=100)
    pain_or_injuries: list[PainOrInjuryInput] = Field(default_factory=list, max_length=50)
    allergies: list[ShortText] = Field(default_factory=list, max_length=100)
    dietary_preferences: list[ShortText] = Field(default_factory=list, max_length=100)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("equipment", mode="before")
    @classmethod
    def normalize_equipment(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip().lower() if isinstance(item, str) else item for item in value]

        return value

    @field_validator(
        "equipment",
        "preferred_exercises",
        "disliked_exercises",
        "allergies",
        "dietary_preferences",
    )
    @classmethod
    def reject_duplicates(cls, value: list[object]) -> list[object]:
        normalized_items = [str(item).casefold() for item in value]
        if len(normalized_items) != len(set(normalized_items)):
            raise ValueError("List items must not contain duplicates")

        return value

    @field_validator("target_date")
    @classmethod
    def reject_past_target_date(cls, value: date | None) -> date | None:
        if value is not None and value < date.today():
            raise ValueError("Target date cannot be in the past")

        return value

    @model_validator(mode="after")
    def reject_conflicting_exercise_preferences(self) -> Self:
        overlap = set(self.preferred_exercises).intersection(self.disliked_exercises)
        if overlap:
            raise ValueError("An exercise cannot be both preferred and disliked")

        return self


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goal_type: GoalTypeValue
    target_date: date | None
    target_weight_kg: Decimal | None
    status: GoalStatusValue


class ConstraintsResponse(BaseModel):
    equipment: list[str]
    preferred_exercises: list[UUID]
    disliked_exercises: list[UUID]
    pain_or_injuries: list[PainOrInjuryInput]
    allergies: list[str]
    dietary_preferences: list[str]


class GoalsAndConstraintsResponse(BaseModel):
    version: int
    goal: GoalResponse
    constraints: ConstraintsResponse
    warnings: list[str]


class GoalCheckResponse(BaseModel):
    valid: bool
    warnings: list[str]
