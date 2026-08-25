from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str | None
    sex: Literal[
        "male",
        "female",
        "other",
        "unspecified",
    ]
    birth_date: date | None
    height_cm: Decimal | None
    experience_level: (
        Literal[
            "beginner",
            "intermediate",
            "advanced",
        ]
        | None
    )
    weekly_training_days: int | None
    session_duration_minutes: int | None
    timezone: str
    version: int


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(
        default=None,
        max_length=80,
    )
    sex: (
        Literal[
            "male",
            "female",
            "other",
            "unspecified",
        ]
        | None
    ) = None
    birth_date: date | None = None
    height_cm: Decimal | None = Field(
        default=None,
        gt=0,
        le=300,
        max_digits=5,
        decimal_places=2,
    )
    experience_level: (
        Literal[
            "beginner",
            "intermediate",
            "advanced",
        ]
        | None
    ) = None
    weekly_training_days: int | None = Field(
        default=None,
        ge=0,
        le=7,
    )
    session_duration_minutes: int | None = Field(
        default=None,
        gt=0,
        le=1440,
    )
    expected_version: int = Field(ge=1)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_empty_sex(cls, value: object) -> object:
        return "unspecified" if value is None else value

    @field_validator("birth_date")
    @classmethod
    def reject_future_birth_date(
        cls,
        value: date | None,
    ) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Birth date cannot be in the future")

        return value

    @model_validator(mode="after")
    def require_updated_field(self) -> Self:
        update_fields = {
            "display_name",
            "sex",
            "birth_date",
            "height_cm",
            "experience_level",
            "weekly_training_days",
            "session_duration_minutes",
        }

        if not self.model_fields_set.intersection(update_fields):
            raise ValueError("At least one profile field must be provided")

        return self
