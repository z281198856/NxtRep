from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nxtrep_backend.domain.confirmation import ConfirmationStatus


class ConfirmationCreate(BaseModel):
    operation: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", max_length=100)
    before: dict[str, Any] | None = None
    after: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2_000)
    impact: str = Field(min_length=1, max_length=2_000)


class ConfirmationDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class ConfirmationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: UUID
    operation: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    reason: str
    impact: str
    status: ConfirmationStatus
    created_at: datetime
    decided_at: datetime | None


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
