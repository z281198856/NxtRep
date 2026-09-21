from typing import TypedDict
from uuid import UUID

from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_planning import (
    PlannedAgentRequest,
)
from nxtrep_backend.services.conversation import AgentConversationContext


class AgentGraphState(TypedDict, total=False):
    user_id: UUID
    request: AgentChatRequest
    streaming: bool
    conversation_context: AgentConversationContext
    planned_request: PlannedAgentRequest
    execution_bundle: AgentExecutionBundle
    response_message: str
