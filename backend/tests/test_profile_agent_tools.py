import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.agents.tools import AgentToolContext, build_tools, groups_for_task
from nxtrep_backend.agents.tools.profile import build_profile_draft_tools
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.profile import ProfileNotFoundError


def test_profile_write_tools_are_available_only_for_profile_drafts():
    context = MagicMock(spec=AgentToolContext)

    def names(task_type):
        task = AgentIntentTask(task_type=task_type, confidence="high", routing_reason="test")
        return {tool.name for tool in build_tools(context, groups=groups_for_task(task))}

    assert {"read_profile_for_update", "propose_profile_update"} <= names("profile_update_draft")
    for task in ("general_question", "structured_data_query", "memory_write", "food_catalog_draft"):
        assert "propose_profile_update" not in names(task)


@pytest.mark.asyncio
async def test_profile_tool_requires_actual_read_and_only_proposes_once(monkeypatch):
    context = MagicMock(spec=AgentToolContext)
    context.profile_service.read_update_snapshot = AsyncMock(
        return_value={"version": 3, "height_cm": "170"}
    )
    context.profile_service.propose_update = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(
        "nxtrep_backend.agents.tools.profile.confirmation_payload",
        lambda _: {"operation_type": "profile_update"},
    )
    read, propose = build_profile_draft_tools(context)
    body = {"changes": {"expected_version": 3, "height_cm": 175}}
    assert (await propose.ainvoke(body))["status"] == "needs_review"
    context.profile_service.propose_update.assert_not_awaited()
    assert (await read.ainvoke({}))["profile"]["version"] == 3
    assert (await propose.ainvoke(body))["status"] == "confirmation_required"
    await propose.ainvoke(body)
    context.profile_service.propose_update.assert_awaited_once()
    submitted = context.profile_service.propose_update.await_args.args[1]
    assert submitted.model_fields_set == {"height_cm", "expected_version"}


@pytest.mark.asyncio
async def test_missing_profile_read_cannot_enable_proposal():
    context = MagicMock(spec=AgentToolContext)
    context.profile_service.read_update_snapshot = AsyncMock(side_effect=ProfileNotFoundError())
    context.profile_service.propose_update = AsyncMock()
    read, propose = build_profile_draft_tools(context)
    assert (await read.ainvoke({}))["status"] == "needs_review"
    await propose.ainvoke({"changes": {"expected_version": 1, "height_cm": 175}})
    context.profile_service.propose_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [False, True])
async def test_profile_handler_does_not_claim_success_without_confirmation(review):
    messages = []
    if review:
        messages.append(
            ToolMessage(
                name="propose_profile_update",
                tool_call_id="test",
                content=json.dumps({"status": "needs_review", "message": "请核对资料"}),
            )
        )
    messages.append(AIMessage(content="资料已经修改。"))
    agent = MagicMock()
    agent.ainvoke = AsyncMock(return_value={"messages": messages})
    branch = AgentBranchInput(
        user_id=uuid4(),
        message="把身高改为175厘米",
        images=(),
        task=AgentIntentTask(
            task_type="profile_update_draft", confidence="high", routing_reason="test"
        ),
    )
    result = await GeneralQuestionBranchHandler(lambda _: agent).execute(branch)
    assert result.status == ("needs_input" if review else "failed")
    assert not result.confirmation_cards
    assert agent.ainvoke.await_count == (1 if review else 2)
