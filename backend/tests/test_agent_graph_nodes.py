from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.nodes import (
    AgentGraphNodes,
    AgentGraphStateError,
)
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentChatRequest,
    AgentConfirmationCard,
    AgentExecutionBundle,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_planning import (
    AgentRequestPlanner,
    PlannedAgentRequest,
)
from nxtrep_backend.services.conversation import AgentConversationContext


def make_dependencies():
    planner = MagicMock(spec=AgentRequestPlanner)
    planner.plan = AsyncMock()
    executor = MagicMock(spec=AgentBranchExecutor)
    executor.execute = AsyncMock()
    synthesizer = MagicMock(spec=AgentResponseSynthesizer)
    synthesizer.synthesize = AsyncMock()
    synthesizer.astream = MagicMock()
    return planner, executor, synthesizer


def make_request() -> AgentChatRequest:
    return AgentChatRequest(message="分析这顿饭")


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
async def test_plan_node_adds_planned_request_to_state() -> None:
    planner, executor, synthesizer = make_dependencies()
    planned_request = make_planned_request()
    planner.plan.return_value = planned_request
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    user_id = uuid4()
    request = make_request()
    conversation_context = AgentConversationContext()

    update = await nodes.plan_request(
        {
            "user_id": user_id,
            "request": request,
            "conversation_context": conversation_context,
        }
    )

    assert update == {"planned_request": planned_request}
    planner.plan.assert_awaited_once_with(
        user_id=user_id,
        request=request,
        conversation_context=conversation_context,
    )
    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_node_adds_execution_bundle_to_state() -> None:
    planner, executor, synthesizer = make_dependencies()
    planned_request = make_planned_request()
    execution_bundle = make_execution_bundle()
    executor.execute.return_value = execution_bundle
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    user_id = uuid4()
    request = make_request()

    update = await nodes.execute_branches(
        {
            "user_id": user_id,
            "request": request,
            "planned_request": planned_request,
        }
    )

    assert update == {"execution_bundle": execution_bundle}
    executor.execute.assert_awaited_once_with(
        user_id=user_id,
        message=request.message,
        planned_request=planned_request,
    )
    planner.plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesis_node_adds_response_message_to_state() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = make_execution_bundle()
    synthesizer.synthesize.return_value = "这顿饭需要确认食物份量。"
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    request = make_request()
    conversation_context = AgentConversationContext()

    update = await nodes.synthesize_response(
        {
            "request": request,
            "execution_bundle": execution_bundle,
            "conversation_context": conversation_context,
        }
    )

    assert update == {"response_message": "这顿饭需要确认食物份量。"}
    synthesizer.synthesize.assert_awaited_once_with(
        user_message=request.message,
        execution_bundle=execution_bundle,
        conversation_context=conversation_context,
    )


@pytest.mark.asyncio
async def test_synthesis_node_returns_single_knowledge_answer_without_model() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "仅根据已审核知识库作答。"},
            )
        ]
    )
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )

    update = await nodes.synthesize_response(
        {
            "request": AgentChatRequest(message="训练问题"),
            "execution_bundle": execution_bundle,
        }
    )

    assert update == {"response_message": "仅根据已审核知识库作答。"}
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_safety_node_validates_execution_before_synthesis() -> None:
    planner, executor, synthesizer = make_dependencies()
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    unsafe = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_measurement_draft",
                status="completed",
                result={"measurement": {}},
            )
        ]
    )

    update = await nodes.validate_execution({"execution_bundle": unsafe})

    branch = update["execution_bundle"].branch_results[0]
    assert branch.status == "failed"
    assert branch.error.code == "UNSAFE_WRITE_RESULT"


@pytest.mark.asyncio
async def test_streaming_synthesis_disables_fallback_to_avoid_mixed_partial_answers() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = make_execution_bundle()

    async def stream_answer(**_kwargs):
        yield "流式"
        yield "回答"

    synthesizer.astream.side_effect = stream_answer
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    request = make_request()
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": request,
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    assert update == {"response_message": "流式回答"}
    synthesizer.astream.assert_called_once_with(
        user_message=request.message,
        execution_bundle=execution_bundle,
        conversation_context=AgentConversationContext(),
        allow_fallback=False,
    )
    assert [call.args[0]["delta"] for call in writer.call_args_list] == ["流式", "回答"]
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_plain_general_question_uses_native_synthesis_stream() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question",
                status="completed",
                result={"response_mode": "direct_general_question"},
            )
        ]
    )

    async def stream_answer(**_kwargs):
        yield "你"
        yield "好"

    synthesizer.astream.side_effect = stream_answer
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    request = AgentChatRequest(message="你好")
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": request,
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    assert update == {"response_message": "你好"}
    assert [call.args[0]["delta"] for call in writer.call_args_list] == ["你", "好"]
    synthesizer.astream.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_direct_answer_is_emitted_on_custom_channel() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "知识库回答"},
            )
        ]
    )
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": AgentChatRequest(message="训练问题"),
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    assert update == {"response_message": "知识库回答"}
    writer.assert_called_once_with(
        {
            "event": "message_delta",
            "node": "synthesize_response",
            "delta": "知识库回答",
        }
    )
    synthesizer.astream.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_failed_vision_branch_uses_deterministic_answer() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_assessment",
                status="failed",
                error=AgentBranchError(
                    code="VISION_ASSESSMENT_INVALID",
                    message="invalid fallback response",
                    retryable=True,
                ),
            )
        ]
    )
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": AgentChatRequest(message="评价一下二头"),
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    expected = "视觉模型这次没有返回完整的评估结果，请重新发送照片后重试。"
    assert update == {"response_message": expected}
    writer.assert_called_once_with(
        {
            "event": "message_delta",
            "node": "synthesize_response",
            "delta": expected,
        }
    )
    synthesizer.astream.assert_not_called()
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", ["general_question", "structured_data_query"])
async def test_streaming_read_only_answer_skips_redundant_model_synthesis(
    task_type: str,
) -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type=task_type,
                status="completed",
                result={"answer": "  已由只读分支生成的回答。  "},
            )
        ]
    )
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": AgentChatRequest(message="请直接回答"),
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    assert update == {"response_message": "已由只读分支生成的回答。"}
    writer.assert_called_once_with(
        {
            "event": "message_delta",
            "node": "synthesize_response",
            "delta": "已由只读分支生成的回答。",
        }
    )
    synthesizer.astream.assert_not_called()
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch_options",
    [
        {"operation_results": [{"status": "saved"}]},
        {
            "confirmation_cards": [
                AgentConfirmationCard(
                    confirmation_id=uuid4(),
                    operation_type="profile_update",
                    status="pending",
                    impact="更新个人资料",
                    expires_at="2026-09-14T12:00:00+08:00",
                    version=1,
                )
            ]
        },
        {"requires_confirmation": True},
    ],
    ids=["operation", "confirmation-card", "confirmation-required"],
)
async def test_read_only_answer_with_side_effect_metadata_still_uses_synthesizer(
    branch_options: dict,
) -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question",
                status="completed",
                result={"answer": "分支原始回答"},
                **branch_options,
            )
        ]
    )
    synthesizer.synthesize.return_value = "包含操作或确认信息的最终回答"
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    request = AgentChatRequest(message="更新并回答")

    update = await nodes.synthesize_response(
        {
            "request": request,
            "execution_bundle": execution_bundle,
        }
    )

    assert update == {"response_message": "包含操作或确认信息的最终回答"}
    synthesizer.synthesize.assert_awaited_once_with(
        user_message=request.message,
        execution_bundle=execution_bundle,
        conversation_context=AgentConversationContext(),
    )


@pytest.mark.asyncio
async def test_streaming_today_training_answer_skips_model_synthesis() -> None:
    planner, executor, synthesizer = make_dependencies()
    execution_bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="structured_data_query",
                status="completed",
                result={
                    "answer": "不应覆盖今日训练专用格式化",
                    "query_kind": "today_training",
                    "active_plan": None,
                    "scheduled_events": [
                        {
                            "status": "planned",
                            "title": "全身训练",
                            "estimated_minutes": 40,
                            "content": {"exercises": []},
                        }
                    ],
                    "active_workout": None,
                },
            )
        ]
    )
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )
    writer = MagicMock()

    update = await nodes.synthesize_response(
        {
            "request": AgentChatRequest(message="今天怎么练？"),
            "execution_bundle": execution_bundle,
            "streaming": True,
        },
        writer,
    )

    response = update["response_message"]
    assert "今天安排了「全身训练」（约 40 分钟）" in response
    assert response != "不应覆盖今日训练专用格式化"
    writer.assert_called_once_with(
        {
            "event": "message_delta",
            "node": "synthesize_response",
            "delta": response,
        }
    )
    synthesizer.astream.assert_not_called()
    synthesizer.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_node_rejects_missing_initial_state() -> None:
    planner, executor, synthesizer = make_dependencies()
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )

    with pytest.raises(AgentGraphStateError, match="user_id and request"):
        await nodes.plan_request({"request": make_request()})

    planner.plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_node_rejects_missing_plan() -> None:
    planner, executor, synthesizer = make_dependencies()
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )

    with pytest.raises(AgentGraphStateError, match="planned_request"):
        await nodes.execute_branches(
            {
                "user_id": uuid4(),
                "request": make_request(),
            }
        )

    executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesis_node_rejects_missing_execution_bundle() -> None:
    planner, executor, synthesizer = make_dependencies()
    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=synthesizer,
    )

    with pytest.raises(AgentGraphStateError, match="execution_bundle"):
        await nodes.synthesize_response({"request": make_request()})

    synthesizer.synthesize.assert_not_awaited()
