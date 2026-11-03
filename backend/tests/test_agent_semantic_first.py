"""The model owns intent decisions; parsing and runtime checks provide evidence."""

import json
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_agent_intent_router import make_dependencies
from test_agent_multiturn_pipeline import card, route_to, tool_context

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentIntentPlan,
    AgentIntentTask,
    AgentTaskType,
)
from nxtrep_backend.schemas.agent_task import AgentTaskCandidate, AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.agent_resolution import resolution_feedback
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


def planner(router, writer=None):
    return AgentRequestPlanner(
        resolver=MagicMock(), intent_router=router,
        context_assembler=SimpleNamespace(load_memories=AsyncMock(return_value=[])),
        state_writer=writer,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", get_args(AgentTaskType))
async def test_every_registered_intent_passes_through_model(kind):
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(kind)))
    result = await planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message="当前用户完整请求"),
        conversation_context=AgentConversationContext(),
    )
    router.route.assert_awaited_once()
    assert result.intent_plan.tasks[0].task_type == kind


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["8个", "60kg", "算了", "继续刚才的训练", "第一个", "你好"])
async def test_short_reply_hints_cannot_override_model_query_decision(message):
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4,
    }})
    messages = ()
    if message == "第一个":
        state.active_task.candidates = [
            AgentTaskCandidate(kind="exercise", id=uuid4(), label=name)
            for name in ("杠铃卧推", "哑铃平板卧推")
        ]
        state.active_task.missing_fields.append("selection")
        messages = (ConversationMessageContext(
            role="assistant", content="1. 杠铃卧推\n2. 哑铃平板卧推",
        ),)
    raw = state.model_dump(mode="json")
    router = SimpleNamespace(route=AsyncMock(return_value=route_to("structured_data_query")))
    result = await planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message=message),
        conversation_context=AgentConversationContext(task_state=raw, recent_messages=messages),
    )
    router.route.assert_awaited_once()
    assert result.intent_plan.tasks[0].task_type == "structured_data_query"
    paused = TaskStateManager.load(result.conversation_context.task_state).suspended_task
    assert paused.status == "suspended" and paused.parameters["weight_kg"] == "55"
    assert "reps" not in paused.parameters and paused.task_id == state.active_task.task_id
    assert raw["active_task"]["status"] == "collecting"


@pytest.mark.asyncio
async def test_model_failure_never_falls_back_to_local_write_intent():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4,
    }})
    writer = AsyncMock()
    router = SimpleNamespace(route=AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(TimeoutError):
        await planner(router, writer).plan(
            user_id=uuid4(), request=AgentChatRequest(message="8次", conversation_id=uuid4()),
            conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
        )
    writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_with_redundant_deferred_task_is_reconsidered_by_model():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "杠铃卧推", "weight_kg": 55, "sets": 4,
    }})
    query = route_to("structured_data_query").tasks[0]
    redundant = route_to("workout_record_draft", {"awaiting_user_details": True},
                         transition="continue").tasks[0]
    model, structured = make_dependencies()
    structured.ainvoke.side_effect = [
        {"parsed": AgentIntentPlan(tasks=[query, redundant])},
        {"parsed": AgentIntentPlan(tasks=[query])},
    ]
    result = await AgentIntentRouter(model).route(
        message="先查今天已记录的热量，先别记训练。", images=[],
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    assert [task.task_type for task in result.tasks] == ["structured_data_query"]
    assert structured.ainvoke.await_count == 2
    review = str(structured.ainvoke.call_args.args[0])
    assert "REDUNDANT_TASK_DEFERRAL" in review


@pytest.mark.asyncio
async def test_query_then_real_continuation_keeps_original_parameters_and_task():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "杠铃卧推", "weight_kg": 55, "sets": 4,
    }})
    query = route_to("structured_data_query").tasks[0]
    continuation = route_to("workout_record_draft", {"reps": 8}, transition="continue").tasks[0]
    router = SimpleNamespace(route=AsyncMock(
        return_value=AgentIntentPlan(tasks=[query, continuation]),
    ))
    result = await planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message="查今天热量，另外卧推每组8次"),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    task = TaskStateManager.load(result.conversation_context.task_state).active_task
    assert task.task_id == state.active_task.task_id and task.status == "ready"
    assert task.parameters["weight_kg"] == "55" and task.parameters["reps"] == 8
    assert not task.missing_fields


@pytest.mark.asyncio
async def test_model_selection_wins_when_display_order_differs_from_search_order():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
    }})
    candidates = [AgentTaskCandidate(kind="exercise", id=uuid4(), label=name)
                  for name in ("杠铃卧推", "上斜哑铃卧推", "哑铃平板卧推")]
    state.active_task.candidates = candidates
    state.active_task.missing_fields = ["selection"]
    state.active_task.status = "collecting"
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(
        "workout_record_draft", {"exercise_name": "哑铃平板卧推"}, transition="continue",
    )))
    result = await planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message="第二个"),
        conversation_context=AgentConversationContext(
            task_state=state.model_dump(mode="json"), recent_messages=(
                ConversationMessageContext(role="assistant", content=(
                    "1. 杠铃卧推\n2. 哑铃平板卧推\n3. 上斜哑铃卧推"
                )),
            ),
        ),
    )
    task = TaskStateManager.load(result.conversation_context.task_state).active_task
    assert task.task_id == state.active_task.task_id
    assert task.entities["exercise_id"] == str(candidates[2].id)
    assert task.parameters["exercise_name"] == "哑铃平板卧推"
    assert task.parameters["weight_kg"] == "55" and not task.missing_fields
    sent = router.route.call_args.kwargs["conversation_context"].input_hints
    assert sent["displayed_selection"]["entities"]["exercise_id"] == str(candidates[2].id)
    assert "selection" not in sent and "entities" not in sent


@pytest.mark.asyncio
async def test_model_reconsiders_target_conflicting_with_displayed_ordinal():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
    }})
    wrong, correct = str(uuid4()), str(uuid4())
    context = AgentConversationContext(task_state=state.model_dump(mode="json"), input_hints={
        "displayed_selection": {"label": "哑铃平板卧推", "entities": {"exercise_id": correct}},
    })
    model, structured = make_dependencies()
    structured.ainvoke.side_effect = [
        {"parsed": route_to("workout_record_draft", entities={"exercise_id": identifier},
                            transition="continue")}
        for identifier in (wrong, correct)
    ]
    result = await AgentIntentRouter(model).route(
        message="第二个", images=[], conversation_context=context,
    )
    assert result.tasks[0].task_update.entities["exercise_id"] == correct
    assert structured.ainvoke.await_count == 2
    assert "DISPLAYED_SELECTION_CONFLICT" in str(structured.ainvoke.call_args.args[0])


@pytest.mark.parametrize("text", [
    "1. 杠铃卧推\n1. 哑铃平板卧推", "1. 杠铃卧推\n2. 杠铃卧推",
    "1. 杠铃卧推\n2. 不存在的动作", "1. 杠铃卧推\n3. 哑铃平板卧推",
])
def test_unreliable_numbered_list_does_not_supply_a_business_target(text):
    state = TaskStateManager.apply_plan({}, "workout_record_draft")
    state.active_task.candidates = [
        AgentTaskCandidate(kind="exercise", id=uuid4(), label=name)
        for name in ("杠铃卧推", "哑铃平板卧推")
    ]
    state.active_task.missing_fields = ["selection"]
    assert not TaskStateManager.displayed_selection(state, "第二个", (
        ConversationMessageContext(role="assistant", content=text),
    ))


@pytest.mark.asyncio
async def test_unresolved_model_selection_is_not_filled_from_parser_ordinal():
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
    }})
    state.active_task.candidates = [
        AgentTaskCandidate(kind="exercise", id=uuid4(), label=name)
        for name in ("杠铃卧推", "上斜哑铃卧推")
    ]
    state.active_task.missing_fields = ["selection"]
    state.active_task.status = "collecting"
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(
        "workout_record_draft", transition="continue",
    )))
    result = await planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message="第二个"),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    task = TaskStateManager.load(result.conversation_context.task_state).active_task
    assert "exercise_id" not in task.entities and task.missing_fields == ["selection"]


@pytest.mark.parametrize("transition", ["correct", "continue"])
def test_canonical_name_change_for_same_entity_does_not_restart_task(transition):
    identifier, confirmation_id = str(uuid4()), str(uuid4())
    state = TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "杠铃卧推", "weight_kg": 55, "sets": 4, "reps": 8,
    }, "entities": {"exercise_id": identifier, "confirmation_id": confirmation_id}})
    state.active_task.status = "awaiting_confirmation"
    result = TaskStateManager.apply_plan(state, "workout_record_draft", AgentTaskUpdate(
        transition=transition, parameters={"exercise_name": "卧推", "weight_kg": 50},
        entities={"exercise_id": identifier} if transition == "continue" else {},
    ))
    assert result.active_task.task_id == state.active_task.task_id
    assert result.active_task.entities["confirmation_id"] == confirmation_id
    assert result.active_task.parameters["weight_kg"] == "50"
    assert result.active_task.parameters["sets"] == 4 and result.active_task.parameters["reps"] == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,operation", [
    ("workout_record_draft", "workout_record_create"),
    ("nutrition_entry_update_draft", "nutrition_entry_update"),
    ("workout_record_update_draft", "workout_record_update"),
    ("confirmation_cancel", "unused"),
])
async def test_unresolved_tool_result_reaches_model_before_final_clarification(
    monkeypatch, kind, operation,
):
    identifier = str(uuid4())
    review = {"status": "needs_review", "missing_fields": ["selection"], "candidates": [
        {"kind": "exercise", "id": identifier, "label": "杠铃卧推"},
    ]}
    unresolved = AgentBranchResult(
        task_type=kind, status="needs_input", missing_fields=["selection"],
        result={"task_answer": "请选择", "task_tool_results": [review]},
    )
    monkeypatch.setattr(
        "nxtrep_backend.services.agent_handlers.general.TaskActionHandler.execute",
        AsyncMock(return_value=unresolved),
    )
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [
        AIMessage(content="你说的是平板杠铃卧推吗？"),
    ]}))
    task = AgentIntentTask(
        task_type=kind, confidence="high", routing_reason="模型理解原请求",
        task_update=AgentTaskUpdate(parameters={"weight_kg": 55, "sets": 4, "reps": 8}),
    )
    result = await GeneralQuestionBranchHandler(
        lambda _: agent, tool_context=tool_context(),
    ).execute(AgentBranchInput(user_id=uuid4(), message="卧推55kg4组8次", task=task, images=()))
    agent.ainvoke.assert_awaited_once()
    messages = agent.ainvoke.call_args.args[0]["messages"]
    text = json.dumps(messages, ensure_ascii=False, default=str)
    assert identifier in text and "杠铃卧推" in text
    assert "current_action_plan" in text
    assert result.status == "needs_input" and not result.confirmation_cards
    assert result.result["saved"] is False


@pytest.mark.asyncio
async def test_model_can_resolve_workout_candidate_in_same_turn(monkeypatch):
    selected = str(uuid4())
    review = {"status": "needs_review", "missing_fields": ["exercise_id"], "candidates": [
        {"exercise_id": selected, "exercise_name": "杠铃卧推"},
        {"exercise_id": str(uuid4()), "exercise_name": "上斜哑铃卧推"},
    ]}
    pending = AgentBranchResult(
        task_type="workout_record_draft", status="needs_input", missing_fields=["selection"],
        result={"task_answer": "请选择", "task_tool_results": [review]},
    )
    monkeypatch.setattr(
        "nxtrep_backend.services.agent_handlers.general.TaskActionHandler.execute",
        AsyncMock(return_value=pending),
    )
    proposal = confirmation_payload(card("workout_record_create", {"request": {
        "exercise_id": selected, "exercise_name": "杠铃卧推",
        "weight_kg": "55", "sets": 4, "reps": 8,
    }}))
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [
        ToolMessage(name="propose_workout_record", tool_call_id="proposal", content=json.dumps({
            "status": "confirmation_required", "confirmation": proposal,
        })),
        AIMessage(content="先按平板杠铃卧推整理成草稿，可以再改。"),
    ]}))
    task = AgentIntentTask(
        task_type="workout_record_draft", confidence="high", routing_reason="记录实际训练",
        task_update=AgentTaskUpdate(parameters={
            "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
        }),
    )
    handler = GeneralQuestionBranchHandler(lambda _: agent, tool_context=tool_context())
    result = await handler.execute(
        AgentBranchInput(user_id=uuid4(), message="卧推55kg4组8次", task=task, images=()),
    )
    assert result.status == "completed" and result.requires_confirmation
    assert result.confirmation_cards[0].after["request"]["exercise_id"] == selected
    assert result.result["semantic_resolution"] == "resolved"
    state = TaskStateManager.apply_plan({}, "workout_record_draft", task.task_update)
    state = TaskStateManager.commit_results(state, cards=result.confirmation_cards)
    assert state.active_task.entities["exercise_id"] == selected
    assert state.active_task.parameters["exercise_name"] == "杠铃卧推"
    assert state.active_task.parameters["weight_kg"] == "55"
    assert state.active_task.status == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_model_clarification_after_successful_lookup_is_not_a_write_failure(monkeypatch):
    monkeypatch.setattr(
        "nxtrep_backend.services.agent_handlers.general.TaskActionHandler.execute",
        AsyncMock(return_value=None),
    )
    identifier = str(uuid4())
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [
        ToolMessage(name="search_exercises", tool_call_id="lookup", content=json.dumps({
            "status": "available", "exercises": [{"id": identifier, "name_zh": "杠铃卧推"}],
        })), AIMessage(content="找到杠铃卧推。是这个动作吗？"),
    ]}))
    task = AgentIntentTask(
        task_type="workout_record_draft", confidence="high", routing_reason="先选动作",
        missing_fields=["selection"], task_update=AgentTaskUpdate(parameters={
            "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
        }),
    )
    handler = GeneralQuestionBranchHandler(lambda _: agent, tool_context=tool_context())
    result = await handler.execute(AgentBranchInput(
        user_id=uuid4(), message="先列候选让我选，先别生成草稿", task=task, images=(),
    ))
    assert result.status == "needs_input" and not result.confirmation_cards
    assert not result.requires_confirmation and result.result["saved"] is False
    state = TaskStateManager.apply_plan({}, task.task_type, task.task_update)
    state = TaskStateManager.commit_results(state, results=[result.result["review"]])
    assert state.active_task.candidates[0].id == UUID(identifier)


@pytest.mark.parametrize("code", [
    "AUTH_ERROR", "PERMISSION_DENIED", "TOOL_OUTCOME_UNKNOWN", "AGENT_TIMEOUT", "TOOL_CALL_LIMIT",
])
def test_auth_unknown_outcome_and_limits_are_not_semantic_retry_candidates(code):
    task = AgentIntentTask(
        task_type="workout_record_draft", confidence="high", routing_reason="test",
    )
    result = AgentBranchResult(
        task_type=task.task_type, status="needs_input", missing_fields=["selection"],
        result={"task_tool_results": [{"status": "needs_review", "error_code": code}]},
    )
    assert resolution_feedback(result, task) is None
