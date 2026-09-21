from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nxtrep_backend.services.memory import MemoryCategory


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MemoryCategory
    content: str = Field(min_length=1, max_length=2000)


class MemoryUpdateRequest(MemoryCreateRequest):
    expected_version: int = Field(ge=1)


class MemoryDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class MemoryResponse(BaseModel):
    id: UUID
    category: str
    content: str
    source: str
    saved_at: datetime
    version: int


class MemoryListResponse(BaseModel):
    list: list[MemoryResponse]
