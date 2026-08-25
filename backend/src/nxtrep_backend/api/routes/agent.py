from fastapi import APIRouter, status

from nxtrep_backend.api.deps import CurrentUserId
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentChatResponse
from nxtrep_backend.services.agent import AgentNotConfiguredError, AgentService

router = APIRouter()


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    body: AgentChatRequest,
    user_id: CurrentUserId,
) -> AgentChatResponse:
    try:
        return await AgentService().chat(user_id=user_id, request=body)
    except AgentNotConfiguredError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AGENT_NOT_CONFIGURED",
            message=str(exc),
        ) from exc
