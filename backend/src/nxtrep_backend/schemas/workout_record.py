from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkoutRecordDraftRequest(StrictModel):
    exercise_id: UUID | None = None
    exercise_name: str | None = Field(default=None, min_length=1, max_length=120)
    weight_kg: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    sets: int | None = Field(default=None, ge=1, le=20)
    reps: int | None = Field(default=None, ge=1, le=100)
    workout_date: date | None = None
    started_at: datetime | None = None
    workout_id: UUID | None = None
    expected_workout_version: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("started_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("训练时间须包含时区")
        return value

    @model_validator(mode="after")
    def date_and_time_agree(self):
        if self.expected_workout_version is not None and self.workout_id is None:
            raise ValueError("训练版本必须与具体训练记录一起提供")
        return self


class WorkoutRecordSetVersion(StrictModel):
    set_id: UUID
    expected_version: int = Field(ge=1)


class WorkoutRecordChangeBase(StrictModel):
    expected_workout_version: int = Field(ge=1)
    set_versions: list[WorkoutRecordSetVersion] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_unique_sets(self):
        if len({item.set_id for item in self.set_versions}) != len(self.set_versions):
            raise ValueError("训练组不能重复选择")
        return self


class WorkoutRecordUpdateRequest(WorkoutRecordChangeBase):
    weight_kg: Decimal | None = Field(default=None, ge=0, max_digits=7, decimal_places=3)
    reps: int | None = Field(default=None, ge=0, le=1000)
    sets: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def require_change(self):
        fields = self.model_fields_set & {"weight_kg", "reps", "sets"}
        if not fields or any(getattr(self, name) is None for name in fields):
            raise ValueError("请提供要更正的重量、次数或组数，不能清空")
        return self


class WorkoutRecordVoidRequest(WorkoutRecordChangeBase):
    pass
