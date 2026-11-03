import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.agents import runtime
from nxtrep_backend.agents.tools.workout import build_workout_draft_tools
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler


def branch(task_type):
    return AgentBranchInput(
        user_id=uuid4(),
        message="请按我的记录生成调整草稿，先不要执行",
        images=(),
        task=AgentIntentTask(
            task_type=task_type, confidence="high", routing_reason="explicit change"
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type,operation,tool",
    [
        ("schedule_change_draft", "calendar_reschedule", "propose_schedule_change"),
        ("training_progression_draft", "training_progression_apply", "propose_progression"),
    ],
)
async def test_training_changes_accept_their_own_confirmation_without_plan_activation(
    task_type, operation, tool
):
    agent = MagicMock()
    agent.ainvoke = AsyncMock(
        return_value={
            "messages": [
                ToolMessage(
                    name=tool,
                    tool_call_id="proposal",
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "draft": {"version": 2},
                            "confirmation": {
                                "confirmation_id": str(uuid4()),
                                "operation_type": operation,
                                "status": "pending",
                                "impact": "确认后执行",
                                "version": 1,
                                "expires_at": "2026-10-06T00:00:00+08:00",
                            },
                        }
                    ),
                ),
                AIMessage(content="调整草稿已创建，等待确认。"),
            ]
        }
    )
    result = await GeneralQuestionBranchHandler(lambda _: agent).execute(branch(task_type))
    assert result.status == "completed"
    assert result.requires_confirmation
    assert result.confirmation_cards[0].operation_type == operation
    agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_warnings_require_alternative_instead_of_confirmation():
    agent = MagicMock()
    agent.ainvoke = AsyncMock(
        return_value={
            "messages": [
                ToolMessage(
                    name="propose_schedule_change",
                    tool_call_id="proposal",
                    content=json.dumps(
                        {
                            "status": "needs_review",
                            "draft": {"warnings": ["合并后训练量增加超过30%"]},
                            "confirmation": None,
                        }
                    ),
                ),
                AIMessage(content="请换一个日期。"),
            ]
        }
    )
    result = await GeneralQuestionBranchHandler(lambda _: agent).execute(
        branch("schedule_change_draft")
    )
    assert result.status == "needs_input"
    assert not result.confirmation_cards
    assert not result.requires_confirmation
    assert result.result["saved"] is False


@pytest.mark.parametrize(
    "task_type,expected",
    [
        ("training_plan_draft", "propose_training_plan"),
        ("schedule_change_draft", "propose_schedule_change"),
        ("training_progression_draft", "propose_progression"),
        ("nutrition_record_draft", "propose_nutrition_entry"),
        ("nutrition_target_draft", "propose_nutrition_target"),
    ],
)
def test_runtime_only_grants_the_requested_proposal(monkeypatch, task_type, expected):
    names = [
        "read_calendar",
        "propose_training_plan",
        "propose_schedule_change",
        "propose_progression",
        "propose_nutrition_entry",
        "propose_nutrition_target",
    ]
    monkeypatch.setattr(
        runtime,
        "build_tools",
        lambda *_args, **_kwargs: [SimpleNamespace(name=name) for name in names],
    )
    create = MagicMock()
    monkeypatch.setattr(runtime, "create_agent", create)
    runtime.build_agent(
        MagicMock(), tool_context=MagicMock(), model=MagicMock(), task_type=task_type
    )
    selected = [item.name for item in create.call_args.kwargs["tools"]]
    assert selected == ["read_calendar", expected]


@pytest.mark.asyncio
async def test_empty_progression_cannot_be_submitted_for_confirmation():
    service = MagicMock()
    service.create_progression_draft = AsyncMock(
        return_value=SimpleNamespace(id=uuid4(), suggestions=[])
    )
    service.submit_progression = AsyncMock()
    tool = build_workout_draft_tools(SimpleNamespace(user_id=uuid4(), workout_service=service))[0]
    result = await tool.ainvoke({"workout_id": str(uuid4())})
    assert result["status"] == "needs_review"
    assert result["confirmation"] is None
    service.submit_progression.assert_not_awaited()
