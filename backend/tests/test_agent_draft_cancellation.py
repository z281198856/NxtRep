import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.agents.tools import AgentToolContext, build_tools, groups_for_task
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentIntentTask
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_safety import AgentExecutionSafetyValidator


def task(name):
    return AgentIntentTask(
        task_type=name, confidence="high", routing_reason="explicit cancellation"
    )


def test_read_only_tasks_cannot_cancel_and_cancel_task_cannot_approve_or_propose():
    for name in ("general_question", "structured_data_query", "knowledge_retrieval"):
        tools = build_tools(MagicMock(spec=AgentToolContext), groups=groups_for_task(task(name)))
        assert "cancel_confirmation" not in {tool.name for tool in tools}
    tools = build_tools(
        MagicMock(spec=AgentToolContext), groups=groups_for_task(task("confirmation_cancel"))
    )
    assert {tool.name for tool in tools} == {
        "cancel_confirmation",
        "read_confirmation_status",
        "list_confirmations",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("executed", [False, True])
async def test_cancel_claim_requires_actual_cancel_tool_result(executed):
    messages = []
    if executed:
        messages.append(
            ToolMessage(
                name="cancel_confirmation",
                tool_call_id="cancel",
                content=json.dumps(
                    {
                        "status": "cancelled",
                        "confirmation": {"confirmation_id": str(uuid4())},
                    }
                ),
            )
        )
    messages.append(AIMessage(content="已取消草稿。"))
    agent = MagicMock()
    agent.ainvoke = AsyncMock(return_value={"messages": messages})
    result = await GeneralQuestionBranchHandler(lambda _: agent).execute(
        AgentBranchInput(
            user_id=uuid4(),
            message="取消刚才的草稿",
            images=(),
            task=task("confirmation_cancel"),
        )
    )
    assert result.status == ("completed" if executed else "failed")
    assert not result.confirmation_cards


def test_safety_rejects_unverified_cancel_success():
    result = AgentExecutionSafetyValidator()._validate_branch(
        AgentBranchResult(
            task_type="confirmation_cancel",
            status="completed",
            result={"message": "已取消"},
        )
    )
    assert result.status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected_answer", [
    ("这份草稿保存了吗？", "待确认区"),
    ("碳水应该不超过六十克", "配菜估算12克"),
])
async def test_list_confirmation_is_a_real_read_and_its_state_reaches_synthesizer(
    message, expected_answer,
):
    card = {"confirmation_id": str(uuid4()), "status": "pending", "version": 1}
    agent = MagicMock()
    agent.ainvoke = AsyncMock(
        return_value={
            "messages": [
                ToolMessage(
                    name="list_confirmations",
                    tool_call_id="read",
                    content=json.dumps(
                        {
                            "status": "available",
                            "confirmations": [card],
                        }
                    ),
                ),
                AIMessage(content="米饭碳水约56克，配菜估算12克，合计约68克。"),
            ]
        }
    )
    result = await GeneralQuestionBranchHandler(lambda _: agent).execute(
        AgentBranchInput(
            user_id=uuid4(),
            message=message,
            images=(),
            task=AgentIntentTask(
                task_type="structured_data_query",
                required_context=["confirmation"],
                confidence="high",
                routing_reason="query saved draft state",
            ),
        )
    )
    assert result.status == "completed"
    assert result.result["queried_records"][0]["confirmations"] == [card]
    assert not GeneralQuestionBranchHandler._read_payload_is_complete(
        "list_confirmations", {"status": "available", "confirmations": [{"status": "pending"}]}
    )
    assert expected_answer in result.result["answer"]
    assert "pending" not in result.result["answer"]


@pytest.mark.parametrize(
    "status,word",
    [
        ("pending", "尚未生效"),
        ("succeeded", "确认生效"),
        ("cancelled", "已取消"),
        ("expired", "已过期"),
    ],
)
def test_confirmation_reply_uses_actual_state_without_technical_statuses(status, word):
    card = {"confirmation_id": str(uuid4()), "status": status, "version": 1}
    messages = [
        ToolMessage(
            name="read_confirmation_status",
            tool_call_id="state",
            content=json.dumps({"status": "available", "confirmation": card}),
        )
    ]
    answer = GeneralQuestionBranchHandler._confirmation_status_answer(messages)
    assert word in answer
    assert status not in answer


def test_ambiguous_confirmation_list_cannot_be_reported_as_one_known_draft():
    cards = [{"confirmation_id": str(uuid4()), "status": "pending", "version": 1} for _ in range(2)]
    messages = [
        ToolMessage(
            name="list_confirmations",
            tool_call_id="state",
            content=json.dumps({"status": "available", "confirmations": cards}),
        )
    ]
    assert GeneralQuestionBranchHandler._confirmation_status_answer(messages) is None
