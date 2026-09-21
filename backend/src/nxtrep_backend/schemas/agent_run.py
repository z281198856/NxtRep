from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentRunCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    status: Literal["running", "succeeded", "failed", "cancel_requested", "cancelled"]
    checkpoint: dict[str, Any]
    result_payload: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    version: int


class AgentToolRunListResponse(BaseModel):
    list: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    has_more: bool
