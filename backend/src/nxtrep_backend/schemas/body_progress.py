from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BodyProgressPhotoCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_asset_id: UUID
    captured_at: datetime
    view: Literal["front", "side", "back", "unknown"] = "unknown"
    notes: str | None = Field(default=None, max_length=2000)
    assessment: dict[str, Any] | None = None

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone offset")
        return value


class BodyProgressPhotoDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class BodyProgressPhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_asset_id: UUID
    captured_at: datetime
    view: str
    notes: str | None
    assessment: dict[str, Any] | None
    version: int
    created_at: datetime


class BodyPhotoUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    content_length: int = Field(gt=0)


class BodyPhotoAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        default="请评估训练相关的体态和肌肉平衡变化。",
        min_length=1,
        max_length=1000,
    )


class BodyPhotoCompareRequest(BodyPhotoAnalysisRequest):
    before_photo_id: UUID
    after_photo_id: UUID
