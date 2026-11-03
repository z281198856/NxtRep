from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.routes import agent
from nxtrep_backend.schemas.agent import AgentChatRequest


@pytest.mark.asyncio
async def test_non_streaming_workflow_timeout_returns_safe_504(monkeypatch):
    service = SimpleNamespace(chat=AsyncMock(side_effect=TimeoutError("private-provider-detail")))
    monkeypatch.setattr(agent, "build_agent_workflow_service", lambda **_: service)
    with pytest.raises(ApiError) as caught:
        await agent.chat(body=AgentChatRequest(message="记午餐"),
                         user_id=uuid4(), session=MagicMock())
    assert caught.value.status_code == 504
    assert caught.value.code == "AGENT_TIMEOUT"
    assert "超时" in caught.value.message and "private" not in caught.value.message
