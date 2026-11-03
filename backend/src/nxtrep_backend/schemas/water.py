from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WaterEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_ml: int = Field(ge=1, le=5000, strict=True)
    consumed_at: AwareDatetime


class WaterEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount_ml: int
    consumed_at: datetime
