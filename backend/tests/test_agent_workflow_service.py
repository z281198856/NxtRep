from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph

from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentChatRequest,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_monitoring import AgentRunMonitor
from nxtrep_backend.services.agent_run import (
    AgentRunCancelledError,
    AgentRunService,
)
from nxtrep_backend.services.agent_workflow import (
    AgentWorkflowResultError,
    AgentWorkflowService,
)
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationService,
)


def make_graph(result: dict) -> MagicMock:
    graph = MagicMock(spec=CompiledStateGraph)
    graph.ainvoke = AsyncMock(return_value=result)
    return graph


def completed_bundle() -> AgentExecutionBundle:
    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question",
                status="completed",
                result={"answer": "ok"},
            )
        ]
    )


def make_conversation_service(conversation_id=None) -> tuple[MagicMock, SimpleNamespace]:
    conversation = SimpleNamespace(id=conversation_id or uuid4())
    service = MagicMock(spec=ConversationService)
    service.begin_turn = AsyncMock(return_value=(conversation, AgentConversationContext()))
    service.finish_turn = AsyncMock()
    return service, conversation


@pytest.mark.asyncio
async def test_chat_runs_graph_and_preserves_conversation_id() -> None:
    conversation_id = uuid4()
    request = AgentChatRequest(
        message="分析这顿饭",
        conversation_id=conversation_id,
    )
    user_id = uuid4()
    graph = make_graph(
        {
            "response_message": "  请确认食物份量后再保存。  ",
            "execution_bundle": completed_bundle(),
        }
    )
    conversations, conversation = make_conversation_service(conversation_id)
    service = AgentWorkflowService(graph, conversations)

    response = await service.chat(
        user_id=user_id,
        request=request,
    )

    effective_request = request.model_copy(update={"conversation_id": conversation_id})
    graph.ainvoke.assert_awaited_once_with(
        {
            "user_id": user_id,
            "request": effective_request,
            "conversation_context": AgentConversationContext(),
        }
    )
    conversations.begin_turn.assert_awaited_once_with(
        user_id=user_id,
        conversation_id=conversation_id,
        user_message=request.message,
        image_asset_ids=[],
    )
    conversations.finish_turn.assert_awaited_once_with(
        conversation=conversation,
        assistant_message="请确认食物份量后再保存。",
    )
    assert response.message == "请确认食物份量后再保存。"
    assert response.conversation_id == conversation_id


@pytest.mark.asyncio
async def test_chat_creates_conversation_id_for_new_conversation() -> None:
    graph = make_graph(
        {
            "response_message": "训练建议",
            "execution_bundle": completed_bundle(),
        }
    )
    conversations, conversation = make_conversation_service()
    service = AgentWorkflowService(graph, conversations)

    response = await service.chat(
        user_id=uuid4(),
        request=AgentChatRequest(message="给我训练建议"),
    )

    assert response.conversation_id == conversation.id
    assert response.message == "训练建议"
    assert response.status == "completed"
    assert len(response.analysis_results) == 1


@pytest.mark.asyncio
async def test_chat_marks_all_failed_branch_response_as_failed_run() -> None:
    failed_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_assessment",
                status="failed",
                error=AgentBranchError(
                    code="VISION_MODEL_BUSY",
                    message="视觉评估服务当前繁忙，请稍后重试",
                    retryable=True,
                ),
            )
        ]
    )
    graph = make_graph(
        {
            "response_message": "视觉评估服务当前繁忙，请稍后重试。",
            "execution_bundle": failed_bundle,
        }
    )
    conversations, _conversation = make_conversation_service()
    run = SimpleNamespace(id=uuid4(), status="running")
    run_service = MagicMock(spec=AgentRunService)
    run_service.start = AsyncMock(return_value=run)
    run_service.checkpoint = AsyncMock()

    async def mark_failed(**_kwargs):
        run.status = "failed"
        return run

    run_service.fail = AsyncMock(side_effect=mark_failed)
    run_service.succeed = AsyncMock()
    monitor = MagicMock(spec=AgentRunMonitor)
    service = AgentWorkflowService(
        graph,
        conversations,
        run_service,
        monitor=monitor,
    )

    response = await service.chat(
        user_id=uuid4(),
        request=AgentChatRequest(message="分析体态"),
    )

    assert response.status == "failed"
    run_service.fail.assert_awaited_once_with(
        run=run,
        error_code="VISION_MODEL_BUSY",
        error_message="视觉评估服务当前繁忙，请稍后重试",
    )
    run_service.succeed.assert_not_awaited()
    monitor.run_failed.assert_called_once()
    monitor.run_succeeded.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "graph_result",
    [
        {},
        {"response_message": "   "},
        {"response_message": ["unexpected", "blocks"]},
        {"response_message": "有效文本"},
    ],
)
async def test_chat_rejects_missing_or_invalid_response(
    graph_result: dict,
) -> None:
    graph = make_graph(graph_result)
    conversations, _conversation = make_conversation_service()
    service = AgentWorkflowService(graph, conversations)

    with pytest.raises(
        AgentWorkflowResultError,
        match="no response message|no execution bundle",
    ):
        await service.chat(
            user_id=uuid4(),
            request=AgentChatRequest(message="分析饮食"),
        )

    conversations.finish_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_reports_graph_nodes_and_final_response() -> None:
    graph = MagicMock(spec=CompiledStateGraph)

    async def updates(*_args, **_kwargs):
        yield (
            "custom",
            {"event": "diagnostic", "node": "plan_request", "delta": "内部路由结果"},
        )
        yield ("updates", {"plan_request": {"planned_request": object()}})
        yield ("updates", {"execute_branches": {"execution_bundle": completed_bundle()}})
        yield ("updates", {"validate_execution": {"execution_bundle": completed_bundle()}})
        yield (
            "custom",
            {"event": "message_delta", "node": "synthesize_response", "delta": "流式"},
        )
        yield (
            "custom",
            {"event": "message_delta", "node": "synthesize_response", "delta": "回答"},
        )
        yield ("updates", {"synthesize_response": {"response_message": "流式回答"}})

    graph.astream = MagicMock(side_effect=updates)
    conversations, conversation = make_conversation_service()
    service = AgentWorkflowService(graph, conversations)

    events = [
        event
        async for event in service.stream(
            user_id=uuid4(),
            request=AgentChatRequest(message="给我建议"),
        )
    ]

    assert [item.event for item in events] == [
        "run_started",
        "node_completed",
        "node_completed",
        "node_completed",
        "message_delta",
        "message_delta",
        "node_completed",
        "completed",
    ]
    assert [item.node for item in events if item.event == "node_completed"] == [
        "plan_request",
        "execute_branches",
        "validate_execution",
        "synthesize_response",
    ]
    assert [item.delta for item in events if item.event == "message_delta"] == [
        "流式",
        "回答",
    ]
    graph.astream.assert_called_once()
    assert graph.astream.call_args.kwargs["stream_mode"] == ["updates", "custom"]
    assert events[-1].response.message == "流式回答"
    assert events[-1].response.conversation_id == conversation.id


@pytest.mark.asyncio
async def test_stream_stops_message_deltas_when_cancellation_is_detected() -> None:
    graph = MagicMock(spec=CompiledStateGraph)

    async def updates(*_args, **_kwargs):
        yield (
            "custom",
            {"event": "message_delta", "node": "synthesize_response", "delta": "第一段"},
        )
        yield (
            "custom",
            {"event": "message_delta", "node": "synthesize_response", "delta": "不应发送"},
        )

    graph.astream = MagicMock(side_effect=updates)
    conversations, _conversation = make_conversation_service()
    run = SimpleNamespace(id=uuid4(), status="running")
    run_service = MagicMock(spec=AgentRunService)
    run_service.start = AsyncMock(return_value=run)
    run_service.check_cancelled = AsyncMock(
        side_effect=[None, AgentRunCancelledError("Agent run was cancelled")]
    )
    service = AgentWorkflowService(
        graph,
        conversations,
        run_service,
        cancel_poll_interval_seconds=0,
    )

    events = [
        event
        async for event in service.stream(
            user_id=uuid4(),
            request=AgentChatRequest(message="停止回答"),
        )
    ]

    assert [item.event for item in events] == [
        "run_started",
        "message_delta",
        "cancelled",
    ]
    assert events[1].delta == "第一段"
    assert events[-1].error_code == "AGENT_RUN_CANCELLED"
    assert run_service.check_cancelled.await_count == 2
    run_service.succeed.assert_not_called()
    run_service.fail.assert_not_called()
    conversations.finish_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_closing_stream_aborts_unfinished_agent_run() -> None:
    graph = MagicMock(spec=CompiledStateGraph)

    async def updates(*_args, **_kwargs):
        yield ("updates", {"plan_request": {"planned_request": object()}})

    graph.astream = MagicMock(side_effect=updates)
    conversations, _conversation = make_conversation_service()
    run = SimpleNamespace(id=uuid4(), status="running")
    run_service = MagicMock(spec=AgentRunService)
    run_service.start = AsyncMock(return_value=run)
    run_service.abort = AsyncMock(side_effect=lambda **_kwargs: setattr(run, "status", "cancelled"))
    monitor = MagicMock(spec=AgentRunMonitor)
    service = AgentWorkflowService(
        graph,
        conversations,
        run_service,
        monitor=monitor,
    )
    stream = service.stream(
        user_id=uuid4(),
        request=AgentChatRequest(message="开始一个长任务"),
    )

    first_event = await anext(stream)
    await stream.aclose()

    assert first_event.event == "run_started"
    run_service.abort.assert_awaited_once_with(
        run=run,
        reason="Agent stream consumer disconnected",
    )
    monitor.run_started.assert_called_once_with(
        run_id=run.id,
        conversation_id=_conversation.id,
    )
    monitor.run_cancelled.assert_called_once()
    assert monitor.run_cancelled.call_args.kwargs["reason"] == "stream_disconnected"
    conversations.finish_turn.assert_not_awaited()
