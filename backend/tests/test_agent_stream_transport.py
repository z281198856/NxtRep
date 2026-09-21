import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from nxtrep_backend.agents.graph import build_agent_execution_graph
from nxtrep_backend.agents.nodes import AgentGraphNodes
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.api.routes.agent import SSE_HEARTBEAT, _stream_sse_events
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentExecutionBundle,
    AgentIntentPlan,
    AgentIntentTask,
    AgentStreamEvent,
)
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_planning import AgentRequestPlanner, PlannedAgentRequest
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import AgentConversationContext, ConversationService


@pytest.mark.asyncio
async def test_transport_emits_heartbeat_while_agent_is_idle() -> None:
    release = asyncio.Event()

    async def events():
        await release.wait()
        yield AgentStreamEvent(event="completed")

    stream = _stream_sse_events(
        events=events(),
        is_disconnected=AsyncMock(return_value=False),
        granularity="chunk",
        heartbeat_interval_seconds=0,
        disconnect_poll_interval_seconds=0,
    )

    assert await anext(stream) == SSE_HEARTBEAT
    await stream.aclose()


@pytest.mark.asyncio
async def test_transport_closes_agent_stream_after_client_disconnects() -> None:
    closed = asyncio.Event()

    async def events():
        try:
            yield AgentStreamEvent(event="run_started")
            await asyncio.Event().wait()
        finally:
            closed.set()

    disconnected = AsyncMock(side_effect=[False, True])
    stream = _stream_sse_events(
        events=events(),
        is_disconnected=disconnected,
        granularity="chunk",
        heartbeat_interval_seconds=60,
        disconnect_poll_interval_seconds=0,
    )

    first = await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)

    assert "event: run_started" in first
    assert closed.is_set()


@pytest.mark.asyncio
async def test_transport_preserves_character_sequence_across_model_chunks() -> None:
    async def events():
        yield AgentStreamEvent(event="message_delta", delta="你好", sequence=1)
        yield AgentStreamEvent(event="message_delta", delta="呀", sequence=2)

    stream = _stream_sse_events(
        events=events(),
        is_disconnected=AsyncMock(return_value=False),
        granularity="character",
    )
    payloads = [item async for item in stream]

    assert len(payloads) == 3
    assert payloads[0].startswith("id: 1\n")
    assert payloads[1].startswith("id: 2\n")
    assert payloads[2].startswith("id: 3\n")
    assert '"delta":"你","sequence":1' in payloads[0]
    assert '"delta":"好","sequence":2' in payloads[1]
    assert '"delta":"呀","sequence":3' in payloads[2]


@pytest.mark.asyncio
async def test_synthetic_workflow_stream_reaches_completed_over_sse() -> None:
    """Exercise graph, native deltas, workflow, and SSE encoding without user data."""
    planned_request = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(
            tasks=[
                AgentIntentTask(
                    task_type="general_question",
                    confidence="high",
                    routing_reason="synthetic transport test",
                )
            ]
        ),
    )
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question",
                status="completed",
                result={"answer": "synthetic branch result"},
            )
        ]
    )
    planner = MagicMock(spec=AgentRequestPlanner)
    planner.plan = AsyncMock(return_value=planned_request)
    executor = MagicMock(spec=AgentBranchExecutor)
    executor.execute = AsyncMock(return_value=execution_bundle)
    graph = build_agent_execution_graph(
        AgentGraphNodes(
            planner=planner,
            executor=executor,
            synthesizer=AgentResponseSynthesizer(
                FakeListChatModel(responses=["合成流式回答"]),
            ),
        )
    )
    conversation = SimpleNamespace(id=uuid4())
    conversations = MagicMock(spec=ConversationService)
    conversations.begin_turn = AsyncMock(
        return_value=(conversation, AgentConversationContext())
    )
    conversations.finish_turn = AsyncMock()
    service = AgentWorkflowService(graph, conversations)

    payloads = [
        payload
        async for payload in _stream_sse_events(
            events=service.stream(
                user_id=uuid4(),
                request=AgentChatRequest(message="合成测试请求"),
            ),
            is_disconnected=AsyncMock(return_value=False),
            granularity="chunk",
        )
    ]
    events = [
        json.loads(
            next(
                line.removeprefix("data: ")
                for line in payload.splitlines()
                if line.startswith("data: ")
            )
        )
        for payload in payloads
    ]

    assert events[0]["event"] == "run_started"
    assert "".join(
        event["delta"] for event in events if event["event"] == "message_delta"
    ) == "synthetic branch result"
    assert events[-1]["event"] == "completed"
    assert events[-1]["response"]["status"] == "completed"
    assert events[-1]["response"]["message"] == "synthetic branch result"
    conversations.finish_turn.assert_awaited_once_with(
        conversation=conversation,
        assistant_message="synthetic branch result",
    )
