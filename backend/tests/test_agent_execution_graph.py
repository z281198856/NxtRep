from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from nxtrep_backend.agents.graph import build_agent_execution_graph
from nxtrep_backend.agents.nodes import AgentGraphNodes
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentExecutionBundle,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_planning import (
    AgentRequestPlanner,
    PlannedAgentRequest,
)


def make_planned_request() -> PlannedAgentRequest:
    return PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(
            tasks=[
                AgentIntentTask(
                    task_type="nutrition_analysis",
                    confidence="high",
                    routing_reason="The user requested nutrition analysis",
                )
            ]
        ),
    )


def make_execution_bundle() -> AgentExecutionBundle:
    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="nutrition_analysis",
                status="completed",
                result={"foods": ["rice", "chicken"]},
            )
        ]
    )


@pytest.mark.asyncio
async def test_graph_runs_plan_then_execute_and_merges_state() -> None:
    events = []
    planned_request = make_planned_request()
    execution_bundle = make_execution_bundle()

    async def plan_side_effect(**_kwargs):
        events.append("plan_request")
        return planned_request

    async def execute_side_effect(**_kwargs):
        assert events == ["plan_request"]
        events.append("execute_branches")
        return execution_bundle

    async def synthesize_side_effect(**_kwargs):
        assert events == ["plan_request", "execute_branches"]
        events.append("synthesize_response")
        return "这顿饭包含米饭和鸡肉，请确认份量后再保存。"

    planner = MagicMock(spec=AgentRequestPlanner)
    planner.plan = AsyncMock(side_effect=plan_side_effect)
    executor = MagicMock(spec=AgentBranchExecutor)
    executor.execute = AsyncMock(side_effect=execute_side_effect)
    synthesizer = MagicMock(spec=AgentResponseSynthesizer)
    synthesizer.synthesize = AsyncMock(side_effect=synthesize_side_effect)
    graph = build_agent_execution_graph(
        AgentGraphNodes(
            planner=planner,
            executor=executor,
            synthesizer=synthesizer,
        )
    )
    user_id = uuid4()
    request = AgentChatRequest(message="分析这顿饭")

    result = await graph.ainvoke(
        {
            "user_id": user_id,
            "request": request,
        }
    )

    assert events == [
        "plan_request",
        "execute_branches",
        "synthesize_response",
    ]
    assert result["user_id"] == user_id
    assert result["request"] == request
    assert result["planned_request"] == planned_request
    assert result["execution_bundle"] == execution_bundle
    assert result["response_message"] == ("这顿饭包含米饭和鸡肉，请确认份量后再保存。")


@pytest.mark.asyncio
async def test_graph_stops_when_planning_fails() -> None:
    planner = MagicMock(spec=AgentRequestPlanner)
    planner.plan = AsyncMock(side_effect=RuntimeError("routing failed"))
    executor = MagicMock(spec=AgentBranchExecutor)
    executor.execute = AsyncMock()
    synthesizer = MagicMock(spec=AgentResponseSynthesizer)
    synthesizer.synthesize = AsyncMock()
    graph = build_agent_execution_graph(
        AgentGraphNodes(
            planner=planner,
            executor=executor,
            synthesizer=synthesizer,
        )
    )

    with pytest.raises(RuntimeError, match="routing failed"):
        await graph.ainvoke(
            {
                "user_id": uuid4(),
                "request": AgentChatRequest(message="分析这顿饭"),
            }
        )

    executor.execute.assert_not_awaited()
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_custom_mode_streams_synthesis_model_character_chunks() -> None:
    planned_request = make_planned_request()
    execution_bundle = make_execution_bundle()
    planner = MagicMock(spec=AgentRequestPlanner)
    planner.plan = AsyncMock(return_value=planned_request)
    executor = MagicMock(spec=AgentBranchExecutor)
    executor.execute = AsyncMock(return_value=execution_bundle)
    graph = build_agent_execution_graph(
        AgentGraphNodes(
            planner=planner,
            executor=executor,
            synthesizer=AgentResponseSynthesizer(
                FakeListChatModel(responses=["逐字"]),
            ),
        )
    )
    chunks: list[str] = []

    async for mode, data in graph.astream(
        {
            "user_id": uuid4(),
            "request": AgentChatRequest(message="给我建议"),
            "streaming": True,
        },
        stream_mode=["updates", "custom"],
    ):
        if mode != "custom":
            continue
        if data.get("event") == "message_delta":
            chunks.append(data["delta"])

    assert "".join(chunks) == "逐字"
