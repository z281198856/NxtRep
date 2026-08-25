from uuid import UUID, uuid4

from nxtrep_backend.agents.runtime import build_agent
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentChatResponse


class AgentNotConfiguredError(RuntimeError):
    pass


class AgentService:
    async def chat(self, user_id: UUID, request: AgentChatRequest) -> AgentChatResponse:
        try:
            agent = build_agent(get_settings(), user_id)
        except ValueError as exc:
            raise AgentNotConfiguredError(str(exc)) from exc

        result = await agent.ainvoke({"messages": [{"role": "user", "content": request.message}]})
        message = result["messages"][-1]
        content = message.content if isinstance(message.content, str) else str(message.content)
        return AgentChatResponse(
            message=content,
            conversation_id=request.conversation_id or uuid4(),
        )
