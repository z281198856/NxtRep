import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.agents.intent_router import AgentIntentRouter, AgentIntentRoutingError
from nxtrep_backend.agents.synthesis import AgentResponseSynthesisError, AgentResponseSynthesizer
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentExecutionBundle,
    AgentIntentTask,
)
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import (
    GeneralQuestionBranchHandler,
    GeneralQuestionResponseError,
)
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)
from nxtrep_backend.services.workout import WorkoutConflictError


class AuthFailure(RuntimeError):
    status_code = 401


def models():
    primary, fallback = MagicMock(spec=BaseChatModel), MagicMock(spec=BaseChatModel)
    primary.ainvoke, fallback.ainvoke = AsyncMock(), AsyncMock()
    return primary, fallback


def bundle():
    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="general_question", status="completed", result={"answer": "按计划训练。"}
            )
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [AuthFailure("opaque provider response"), WorkoutConflictError("版本变化")]
)
async def test_intent_router_does_not_retry_auth_or_business_errors(error):
    primary, fallback = models()
    first, second = MagicMock(), MagicMock()
    first.ainvoke = AsyncMock(side_effect=error)
    second.ainvoke = AsyncMock()
    primary.with_structured_output.return_value = first
    fallback.with_structured_output.return_value = second
    with pytest.raises(AgentIntentRoutingError):
        await AgentIntentRouter(primary, fallback).route(
            message="把我的昵称改为验收昵称。", images=[]
        )
    first.ainvoke.assert_awaited_once()
    second.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [AuthFailure("opaque provider response"), WorkoutConflictError("版本变化")]
)
async def test_response_synthesizer_does_not_retry_auth_or_business_errors(error):
    primary, fallback = models()
    primary.ainvoke.side_effect = error
    with pytest.raises(AgentResponseSynthesisError):
        await AgentResponseSynthesizer(primary, fallback).synthesize(
            user_message="继续", execution_bundle=bundle()
        )
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [AuthFailure("opaque provider response"), WorkoutConflictError("版本变化")]
)
async def test_streaming_synthesizer_does_not_retry_auth_or_business_errors(error):
    primary, fallback = models()
    calls = []

    async def failed_stream(_messages):
        calls.append("primary")
        raise error
        yield AIMessage(content="unreachable")

    async def fallback_stream(_messages):
        calls.append("fallback")
        yield AIMessage(content="不应调用")

    primary.astream.side_effect, fallback.astream.side_effect = failed_stream, fallback_stream
    with pytest.raises(AgentResponseSynthesisError):
        _ = [
            chunk
            async for chunk in AgentResponseSynthesizer(primary, fallback).astream(
                user_message="继续", execution_bundle=bundle()
            )
        ]
    assert calls == ["primary"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [AuthFailure("opaque provider response"), WorkoutConflictError("版本变化")]
)
async def test_general_handler_does_not_rebuild_or_fallback_on_auth_or_business_error(error):
    first, second = MagicMock(), MagicMock()
    first.ainvoke, second.ainvoke = AsyncMock(side_effect=error), AsyncMock()
    handler = GeneralQuestionBranchHandler(
        lambda _: first, lambda _: second, knowledge_retrieval_enabled=False
    )
    request = AgentBranchInput(
        user_id=uuid4(),
        message="深蹲应该怎样呼吸？",
        images=(),
        task=AgentIntentTask(
            task_type="general_question",
            required_context=["profile"],
            confidence="high",
            routing_reason="test",
        ),
    )
    with pytest.raises(GeneralQuestionResponseError):
        await handler.execute(request)
    first.ainvoke.assert_awaited_once()
    second.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_slot,bad_value",
    [
        ("weight_kg", -1),
        ("weight_kg", None),
        ("weight_kg", True),
        ("weight_kg", "NaN"),
        ("sets", 2.5),
        ("sets", 0),
        ("reps", 1001),
        ("amount_g", "-10"),
    ],
)
async def test_invalid_correction_clears_previous_value_and_requests_input_without_tools(
    bad_slot, bad_value
):
    active = AgentTask(
        task_type="workout_record_draft",
        parameters={
            "exercise_name": "杠铃卧推",
            "weight_kg": "60",
            "sets": 4,
            "reps": 8,
            "amount_g": "200",
        },
        status="ready",
    )
    update = AgentTaskUpdate(transition="correct", parameters={bad_slot: bad_value})
    assert bad_slot in update.invalid_fields
    state = TaskStateManager.apply_plan(
        {"active_task": active.model_dump(mode="json")}, "workout_record_draft", update
    )
    assert bad_slot not in state.active_task.parameters
    assert bad_slot in state.active_task.missing_fields
    assert state.active_task.status == "collecting"
    context = MagicMock(spec=AgentToolContext)
    request = AgentBranchInput(
        user_id=uuid4(),
        message="不对，请更正参数",
        images=(),
        task=AgentIntentTask(
            task_type="workout_record_draft",
            confidence="high",
            routing_reason="test",
            missing_fields=state.active_task.missing_fields,
            task_update=update,
        ),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    result = await TaskActionHandler(context).execute(request)
    assert result.status == "needs_input" and bad_slot in result.missing_fields
    assert result.operation_results == []
    context.workout_record_service.assert_not_called()


def test_continue_or_correct_cannot_replace_bound_entity_with_an_llm_invented_target():
    original = str(uuid4())
    active = AgentTask(
        task_type="nutrition_entry_update_draft",
        entities={"entry_id": original},
        parameters={"amount_g": "200"},
        status="completed",
    )
    for transition in ("continue", "correct"):
        state = TaskStateManager.apply_plan(
            {"active_task": active.model_dump(mode="json")},
            "nutrition_entry_update_draft",
            AgentTaskUpdate(
                transition=transition,
                entities={"entry_id": str(uuid4())},
                parameters={"amount_g": "250"},
            ),
        )
        assert state.active_task.entities["entry_id"] == original
        assert "selection" in state.active_task.missing_fields
        assert state.active_task.current_step == "clarify_target"


@pytest.mark.asyncio
async def test_checkpoint_persists_ids_sanitized_snapshots_task_transition_and_action_plan():
    repository = MagicMock(spec=SqlAlchemyAgentRunRepository)
    repository.refresh_locked, repository.commit = AsyncMock(), AsyncMock()
    service = AgentRunService(repository)
    conversation_id, turn_id, task_id, call_id, trace_id = [uuid4() for _ in range(5)]
    run = AgentRun(
        id=trace_id,
        user_id=uuid4(),
        conversation_id=conversation_id,
        status="running",
        request_payload={},
        checkpoint={},
        started_at=datetime.now(UTC),
        version=1,
    )
    active = AgentTask(
        task_id=task_id,
        task_type="workout_record_draft",
        status="collecting",
        parameters={"exercise_name": "卧推"},
        missing_fields=["weight_kg", "sets", "reps"],
    )
    journal = {
        "tool_runs": [
            {
                "tool_name": "read_active_workout",
                "status": "available",
                "tool_call_id": str(call_id),
                "tool_call_id_source": "gateway",
                "conversation_id": str(conversation_id),
                "turn_id": str(turn_id),
                "task_id": str(task_id),
                "trace_id": str(trace_id),
                "arguments_snapshot": {
                    "workout_id": str(uuid4()),
                    "notes": "never log private prose",
                },
                "result_snapshot": {"status": "available", "api_key": "never log credential"},
            }
        ],
        "task_state": {"active_task": active.model_dump(mode="json")},
        "action_plan": {
            "tasks": [
                {
                    "task_type": "workout_record_draft",
                    "confidence": "high",
                    "routing_reason": "missing params",
                }
            ]
        },
    }
    await service.checkpoint(run=run, node="execute_branches", journal=journal)
    stored = run.checkpoint["tool_runs"][0]
    assert stored["tool_call_id"] == str(call_id) and stored["task_id"] == str(task_id)
    assert stored["turn_id"] == str(turn_id) and stored["trace_id"] == str(trace_id)
    assert stored["conversation_id"] == str(conversation_id)
    serialized = json.dumps(stored, ensure_ascii=False)
    assert "never log private prose" not in serialized and "never log credential" not in serialized
    assert run.checkpoint["state_changes"][-1]["to"]["missing_fields"] == [
        "weight_kg",
        "sets",
        "reps",
    ]
    assert run.checkpoint["action_plan"]["tasks"][0]["task_type"] == "workout_record_draft"


@pytest.mark.asyncio
async def test_general_retry_rebounds_long_tool_history_before_next_model_invocation():
    call = AIMessage(
        content="", tool_calls=[{"id": "oversized", "name": "read_food_catalog", "args": {}}]
    )
    tool_result = ToolMessage(
        content=json.dumps({"status": "available", "data": "x" * 48_000}),
        tool_call_id="oversized",
        name="read_food_catalog",
    )
    agent = MagicMock()
    agent.ainvoke = AsyncMock(
        side_effect=[
            {"messages": [call, tool_result, AIMessage(content="还没创建草稿")]},
            {"messages": [AIMessage(content="没有创建草稿，请核对")]},
        ]
    )
    request = AgentBranchInput(
        user_id=uuid4(),
        message="记录午饭",
        images=(),
        task=AgentIntentTask(
            task_type="nutrition_record_draft", confidence="high", routing_reason="test"
        ),
        conversation_context=AgentConversationContext(
            summary="旧历史" * 12_000,
            recent_messages=tuple(
                ConversationMessageContext("assistant", "饮食信息" * 2000) for _ in range(30)
            ),
        ),
    )
    await GeneralQuestionBranchHandler(lambda _: agent, knowledge_retrieval_enabled=False).execute(
        request
    )
    assert agent.ainvoke.await_count == 2
    second = agent.ainvoke.await_args_list[1].args[0]["messages"]
    total = sum(
        len(
            json.dumps(
                message.model_dump(mode="json") if hasattr(message, "model_dump") else message,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        + 1
        for message in second
    )
    assert total <= 24_000
    assert not any(
        isinstance(message, ToolMessage) and message.tool_call_id == "oversized"
        for message in second
    )
