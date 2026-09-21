from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.confirmation import build_confirmation_tools
from nxtrep_backend.services.confirmation import DatabaseConfirmationService


def make_confirmation():
    return SimpleNamespace(
        id=uuid4(),
        operation_type="training_plan_activate",
        status="pending",
        before=None,
        after={"draft_id": "draft"},
        impact="activate plan",
        expires_at=datetime(2026, 9, 4, tzinfo=UTC),
        version=1,
    )


@pytest.mark.asyncio
async def test_read_confirmation_status_binds_current_user() -> None:
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    context.confirmation_service = MagicMock(spec=DatabaseConfirmationService)
    context.confirmation_service.get = AsyncMock(return_value=make_confirmation())
    current_tool = build_confirmation_tools(context)[0]
    confirmation_id = uuid4()

    result = await current_tool.ainvoke({"confirmation_id": str(confirmation_id)})

    assert result["status"] == "available"
    context.confirmation_service.get.assert_awaited_once_with(
        user_id=context.user_id,
        confirmation_id=confirmation_id,
    )
    assert "user_id" not in current_tool.args
