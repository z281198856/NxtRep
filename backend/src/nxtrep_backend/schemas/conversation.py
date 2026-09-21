from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nxtrep_backend.schemas.agent import AgentContextHints


class AgentConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class AgentConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8_000)
    image_asset_ids: list[UUID] = Field(default_factory=list, max_length=4)
    context_hints: AgentContextHints = Field(default_factory=AgentContextHints)

    @field_validator("image_asset_ids")
    @classmethod
    def require_unique_image_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("image_asset_ids must be unique")
        return value


class AgentConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    status: str
    summary: str | None
    last_message_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class AgentConversationListResponse(BaseModel):
    list: list[AgentConversationResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class AgentConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "archived"] | None = None
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "AgentConversationUpdateRequest":
        if self.title is None and self.status is None:
            raise ValueError("title or status is required")
        return self


class AgentConversationDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    sequence: int
    image_asset_ids: list[str]
    created_at: datetime


class AgentMessageListResponse(BaseModel):
    list: list[AgentMessageResponse]
    next_sequence: int | None
    has_more: bool
