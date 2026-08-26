from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BodyMeasurementCreateRequest(StrictModel):
    measured_at: datetime
    weight_kg: Decimal | None = Field(default=None, gt=0, le=500)
    waist_cm: Decimal | None = Field(default=None, gt=0, le=400)
    neck_cm: Decimal | None = Field(default=None, gt=0, le=200)
    hip_cm: Decimal | None = Field(default=None, gt=0, le=400)
    source: str = Field(min_length=1, max_length=30)
    conditions: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_values(self) -> "BodyMeasurementCreateRequest":
        if all(
            value is None for value in (self.weight_kg, self.waist_cm, self.neck_cm, self.hip_cm)
        ):
            raise ValueError("at least one body measurement is required")
        return self


class BodyMeasurementUpdateRequest(StrictModel):
    measured_at: datetime | None = None
    weight_kg: Decimal | None = Field(default=None, gt=0, le=500)
    waist_cm: Decimal | None = Field(default=None, gt=0, le=400)
    neck_cm: Decimal | None = Field(default=None, gt=0, le=200)
    hip_cm: Decimal | None = Field(default=None, gt=0, le=400)
    source: str | None = Field(default=None, min_length=1, max_length=30)
    conditions: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)


class BodyMeasurementResponse(BaseModel):
    id: UUID
    measured_at: datetime
    weight_kg: Decimal | None
    waist_cm: Decimal | None
    neck_cm: Decimal | None
    hip_cm: Decimal | None
    source: str
    conditions: str | None
    notes: str | None
    version: int


class BodyMeasurementListResponse(BaseModel):
    list: list[BodyMeasurementResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class NavyBodyFatRequest(StrictModel):
    sex: Literal["male", "female"]
    height_cm: Decimal = Field(gt=0, le=300)
    waist_cm: Decimal = Field(gt=0, le=400)
    neck_cm: Decimal = Field(gt=0, le=200)
    hip_cm: Decimal | None = Field(default=None, gt=0, le=400)
    save: bool = False

    @model_validator(mode="after")
    def validate_dimensions(self) -> "NavyBodyFatRequest":
        if self.sex == "female" and self.hip_cm is None:
            raise ValueError("hip_cm is required for female calculations")
        circumference = self.waist_cm - self.neck_cm
        if self.sex == "female":
            circumference += self.hip_cm or Decimal("0")
        if circumference <= 0:
            raise ValueError("circumference inputs are not physically valid")
        return self


class NavyBodyFatResponse(BaseModel):
    method: Literal["navy"] = "navy"
    value_percent: Decimal
    range_min_percent: Decimal
    range_max_percent: Decimal
    confidence: Literal["medium"] = "medium"
    disclaimer: str = "结果仅用于观察趋势，不是医学测量"


class ProgressOverviewResponse(BaseModel):
    training: dict
    nutrition: dict
    body: dict


class BodyTrendPoint(BaseModel):
    date: date
    raw_value: Decimal
    smoothed_value: Decimal


class BodyTrendResponse(BaseModel):
    metric: str
    window: str
    points: list[BodyTrendPoint]


class PersonalRecordResponse(BaseModel):
    id: UUID
    exercise_id: UUID | None
    exercise_name: str
    record_type: str
    value: Decimal
    occurred_at: datetime
    workout_id: UUID
    set_id: UUID


class PersonalRecordListResponse(BaseModel):
    list: list[PersonalRecordResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
