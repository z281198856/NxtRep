from uuid import UUID

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    conversation_id: UUID | None = None


class AgentChatResponse(BaseModel):
    message: str
    conversation_id: UUID
