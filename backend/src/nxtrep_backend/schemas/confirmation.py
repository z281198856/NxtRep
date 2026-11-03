from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConfirmationSubmitResponse(BaseModel):
    confirmation_id: UUID
    operation_type: str
    status: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    impact: str


class ConfirmationListItem(BaseModel):
    id: UUID
    operation_type: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    reason: str
    impact: str
    status: str
    version: int
    expires_at: datetime


class ConfirmationListResponse(BaseModel):
    list: list[ConfirmationListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class ConfirmationApproveRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ConfirmationRejectRequest(ConfirmationApproveRequest):
    reason: str | None = Field(default=None, max_length=1000)


class ConfirmationDecisionResponse(BaseModel):
    id: UUID
    status: str
    result: dict[str, Any] | None = None
    executed_at: datetime | None = None
    version: int
