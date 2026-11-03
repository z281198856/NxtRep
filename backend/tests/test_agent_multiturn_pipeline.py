"""Multi-turn evaluation of the real planner, graph nodes and tool handler.

The router is scripted so tests measure deterministic continuity rather than a
provider's stochastic language understanding. PostgreSQL cases cover real writes.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.graph import build_agent_execution_graph
from nxtrep_backend.agents.nodes import AgentGraphNodes
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext


def route_to(task_type, parameters=None, entities=None, transition="new", missing_fields=None):
    return AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type=task_type,
                confidence="high",
                routing_reason="多轮验收路由fixture",
                task_update=AgentTaskUpdate(
                    transition=transition,
                    parameters=parameters or {},
                    entities=entities or {},
                    missing_fields=missing_fields or [],
                ),
            )
        ]
    )


def make_planner(router, state_writer=None):
    # A scripted model answers simple slot/lifecycle turns using the same context
    # hints a real model sees. The production planner still invokes this model on
    # every turn. Explicit scripts are consumed for the remaining semantic turns.
    router.semantic_calls = []

    class FixtureModel:
        async def route(self, **kwargs):
            router.semantic_calls.append(kwargs)
            context = kwargs["conversation_context"]
            hints = context.input_hints
            state = TaskStateManager.load(context.task_state)
            active = state.active_task
            # This fixture model interprets simple choices itself. Production hints
            # deliberately omit selections derived only from raw candidate order.
            selection = TaskStateManager.prepare_turn(
                context.task_state, kwargs["message"],
            ).selection
            if hints.get("transition") == "resume":
                active = state.suspended_task or active
            if active and (
                hints.get("parameters") or hints.get("handled") or selection
                or hints.get("transition") == "cancel"
            ):
                kind = active.task_type
                transition = hints.get("transition") or "continue"
                selected_entities = TaskStateManager.prepare_turn(
                    context.task_state, kwargs["message"],
                ).entities if selection else {}
                entities = {**active.entities, **selected_entities, **hints.get("entities", {})}
                parameters = hints.get("parameters", {})
                if selection and selection.kind in {"meal_item", "food_item", "exercise"}:
                    key = "exercise_name" if selection.kind == "exercise" else "food_name"
                    parameters = {key: selection.label, **parameters}
                if transition == "correct" and kind == "workout_record_draft" and entities.get(
                    "workout_exercise_id"
                ):
                    kind = "workout_record_update_draft"
                if parameters.get("amount_g") is not None and entities.get("entry_id"):
                    kind = "nutrition_entry_update_draft"
                if transition == "cancel":
                    if active.status == "awaiting_confirmation" or any(
                        c.kind == "confirmation" for c in active.candidates
                    ):
                        kind = "confirmation_cancel"
                    elif active.status == "completed":
                        kind = (
                            "workout_record_void_draft" if kind.startswith("workout_")
                            else "nutrition_entry_delete_draft"
                        )
                    else:
                        kind = "general_question"
                return route_to(
                    kind, parameters, entities, transition,
                    ["selection"] if hints.get("clarification_required") else [],
                )
            return await router.route(**kwargs)

    assembler = SimpleNamespace(load_memories=AsyncMock(return_value=[]))
    return AgentRequestPlanner(
        resolver=MagicMock(),
        intent_router=FixtureModel(),
        context_assembler=assembler,
        state_writer=state_writer,
    )


class ContinuationHandler:
    def __init__(self, tool_context):
        self.actions = TaskActionHandler(tool_context)

    async def execute(self, request):
        result = await self.actions.execute(request)
        if result is None and request.task.missing_fields:
            return AgentBranchResult(
                task_type=request.task.task_type,
                status="needs_input",
                missing_fields=request.task.missing_fields,
                result={"task_answer": "请补充这项任务仍缺少的必要信息。"},
            )
        return result or AgentBranchResult(
            task_type=request.task.task_type,
            status="completed",
            result={"task_answer": "通用知识答复"},
        )


def make_graph(router, context, state_writer=None):
    handler = ContinuationHandler(context)
    executor = AgentBranchExecutor(
        {
            kind: handler
            for kind in (
                "workout_record_draft",
                "workout_record_update_draft",
                "workout_record_void_draft",
                "nutrition_entry_update_draft",
                "nutrition_entry_delete_draft",
                "confirmation_cancel",
                "general_question",
                "training_plan_draft",
            )
        }
    )
    return build_agent_execution_graph(
        AgentGraphNodes(
            planner=make_planner(router, state_writer),
            executor=executor,
            synthesizer=MagicMock(),
        )
    )


def tool_context(user_id=None, workout_record_service=None, **services):
    names = (
        "profile_service",
        "goals_service",
        "exercises_service",
        "training_service",
        "workout_service",
        "nutrition_service",
        "body_service",
        "confirmation_service",
        "memory_service",
    )
    return AgentToolContext(
        user_id=user_id or uuid4(),
        workout_record_service=workout_record_service,
        **{name: services.get(name, MagicMock()) for name in names},
    )


def card(operation, after=None):
    return SimpleNamespace(
        id=uuid4(),
        operation_type=operation,
        status="pending",
        before=None,
        after=after or {},
        impact="确认后生效",
        version=1,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


class Pipeline:
    def __init__(self, graph, user_id, context=None, *, occurred_at=None):
        self.graph, self.user_id = graph, user_id
        self.context = context or AgentConversationContext()
        self.occurred_at = occurred_at

    async def turn(self, message):
        result = await self.graph.ainvoke(
            {
                "user_id": self.user_id,
                "request": AgentChatRequest(
                    message=message, context_hints={"occurred_at": self.occurred_at}
                ),
                "conversation_context": self.context,
            }
        )
        self.context = result["conversation_context"]
        return result

    @property
    def task(self):
        return TaskStateManager.load(self.context.task_state).active_task


@pytest.mark.asyncio
async def test_slots_use_one_task_and_call_real_registered_tool_only_when_complete():
    router = SimpleNamespace(
        route=AsyncMock(return_value=route_to("workout_record_draft", {"exercise_name": "卧推"}))
    )
    service = SimpleNamespace(propose_record=AsyncMock(return_value=card("workout_record_create")))
    context = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    first = await pipeline.turn("帮我记录今天卧推")
    task_id = pipeline.task.task_id
    assert first["execution_bundle"].branch_results[0].status == "needs_input"
    await pipeline.turn("60kg")
    assert pipeline.task.parameters["weight_kg"] == "60"
    assert pipeline.task.missing_fields == ["sets", "reps"]
    service.propose_record.assert_not_awaited()
    last = await pipeline.turn("四组每组8个")
    assert pipeline.task.task_id == task_id
    assert pipeline.task.status == "awaiting_confirmation"
    assert len(last["execution_bundle"].branch_results[0].confirmation_cards) == 1
    router.route.assert_awaited_once()
    assert len(router.semantic_calls) == 3
    submitted = service.propose_record.call_args.args[1]
    assert submitted.weight_kg == 60 and submitted.sets == 4 and submitted.reps == 8


@pytest.mark.asyncio
async def test_cancel_collecting_task_never_calls_a_create_tool():
    router = SimpleNamespace(
        route=AsyncMock(return_value=route_to("workout_record_draft", {"exercise_name": "卧推"}))
    )
    service = SimpleNamespace(propose_record=AsyncMock())
    context = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    await pipeline.turn("记录卧推")
    await pipeline.turn("60kg")
    result = await pipeline.turn("算了，不记了")
    assert pipeline.task.status == "cancelled"
    assert "取消" in result["response_message"]
    assert pipeline.task.missing_fields == []
    service.propose_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_interruption_and_resume_keep_original_plan_parameters():
    router = SimpleNamespace(
        route=AsyncMock(
            side_effect=[
                route_to(
                    "training_plan_draft",
                    {"muscle_group": "chest", "duration_minutes": 45},
                    missing_fields=["injury_clearance"],
                ),
                route_to("general_question"),
            ]
        )
    )
    context = tool_context()
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    await pipeline.turn("制定今天胸部训练")
    task_id = pipeline.task.task_id
    await pipeline.turn("一份鸡腿饭多少热量？")
    state = TaskStateManager.load(pipeline.context.task_state)
    assert state.active_task is None and state.suspended_task.task_id == task_id
    resumed = await pipeline.turn("继续刚才的训练")
    assert pipeline.task.task_id == task_id
    assert pipeline.task.parameters["duration_minutes"] == 45
    assert pipeline.task.missing_fields == ["injury_clearance"]
    assert resumed["execution_bundle"].branch_results[0].status == "needs_input"
    assert router.route.await_count == 2


@pytest.mark.asyncio
async def test_modify_completed_record_reads_ids_then_updates_without_recreating():
    workout, item = str(uuid4()), str(uuid4())
    set_versions = [{"set_id": str(uuid4()), "expected_version": 1}]
    service = SimpleNamespace(
        propose_record=AsyncMock(),
        read_for_change=AsyncMock(
            return_value={
                "status": "available",
                "selected_record": {
                    "workout_id": workout,
                    "workout_exercise_id": item,
                    "expected_workout_version": 2,
                    "exercise_name": "卧推",
                    "set_versions": set_versions,
                },
            }
        ),
        propose_change=AsyncMock(
            return_value=card(
                "workout_record_update", {"workout_id": workout, "workout_exercise_id": item}
            )
        ),
    )
    task = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {
            "parameters": {
                "exercise_name": "卧推",
                "weight_kg": "60",
                "sets": 4,
                "reps": 8,
            }
        },
    )
    task = TaskStateManager.commit_results(
        task, [{"success": True, "workout_id": workout, "workout_exercise_id": item}]
    )
    router = SimpleNamespace(route=AsyncMock())
    context = tool_context(workout_record_service=service)
    pipeline = Pipeline(
        make_graph(router, context),
        context.user_id,
        AgentConversationContext(task_state=task.model_dump(mode="json")),
    )
    result = await pipeline.turn("不对，是55kg")
    assert result["execution_bundle"].branch_results[0].status == "completed"
    service.propose_record.assert_not_awaited()
    service.read_for_change.assert_awaited_once()
    changes = service.propose_change.call_args.args[-1]
    assert changes.weight_kg == 55
    assert changes.model_fields_set.intersection({"weight_kg", "reps"}) == {"weight_kg"}
    assert pipeline.task.entities["workout_id"] == workout
    assert pipeline.task.task_id == task.active_task.task_id


@pytest.mark.asyncio
async def test_ambiguous_deletion_cannot_be_converted_into_a_guess_by_router():
    entry = str(uuid4())
    state = TaskStateManager.apply_plan({}, "nutrition_entry_update_draft")
    state = TaskStateManager.commit_results(
        state,
        [
            {
                "status": "available",
                "selected_entry": {
                    "entry_id": entry,
                    "items": [{"name": "米饭"}, {"name": "鸡胸肉"}],
                },
            }
        ],
    )
    # Deliberately unsafe fallback: preflight must stop this before a guessed delete.
    router = SimpleNamespace(
        route=AsyncMock(
            return_value=route_to("nutrition_entry_delete_draft", entities={"entry_id": entry})
        )
    )
    context = tool_context()
    result = await make_planner(router).plan(
        user_id=context.user_id,
        request=AgentChatRequest(message="把刚才那个删了"),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    assert result.intent_plan.tasks[0].missing_fields == ["selection"]
    router.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_append_exercise_has_fresh_quantities_but_reuses_session_id():
    workout, item = str(uuid4()), str(uuid4())
    state = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {
            "parameters": {
                "exercise_name": "卧推",
                "weight_kg": "55",
                "sets": 4,
                "reps": 8,
                "workout_date": "2026-10-08",
            }
        },
    )
    state = TaskStateManager.commit_results(
        state, [{"success": True, "workout_id": workout, "workout_exercise_id": item}]
    )
    router = SimpleNamespace(
        route=AsyncMock(
            return_value=route_to("workout_record_draft", {"exercise_name": "上斜卧推"})
        )
    )
    context = tool_context()
    planned = await make_planner(router).plan(
        user_id=context.user_id,
        request=AgentChatRequest(message="再加一个上斜卧推"),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    task = planned.intent_plan.tasks[0]
    assert task.task_update.entities["workout_id"] == workout
    assert not task.task_update.entities.get("workout_exercise_id")
    assert not any(name in task.task_update.parameters for name in ("weight_kg", "sets", "reps"))
    assert task.missing_fields == ["weight_kg", "sets", "reps"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "succeeded"])
async def test_resume_existing_confirmation_never_reproposes_record(status):
    confirmation = card("workout_record_create")
    confirmation.status = status
    service = SimpleNamespace(propose_record=AsyncMock())
    commands = SimpleNamespace(get=AsyncMock(return_value=confirmation))
    context = tool_context(workout_record_service=service, confirmation_service=commands)
    state = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {
            "parameters": {
                "exercise_name": "卧推",
                "weight_kg": "60",
                "sets": 4,
                "reps": 8,
            }
        },
    )
    state.active_task.entities["confirmation_id"] = str(confirmation.id)
    state.active_task.status = "completed" if status == "succeeded" else "awaiting_confirmation"
    state.suspended_task, state.active_task = state.active_task, None
    router = SimpleNamespace(route=AsyncMock())
    pipeline = Pipeline(
        make_graph(router, context),
        context.user_id,
        AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    result = await pipeline.turn("继续刚才的训练")
    assert result["execution_bundle"].branch_results[0].status == "completed"
    service.propose_record.assert_not_awaited()
    assert pipeline.task.status == (
        "completed" if status == "succeeded" else "awaiting_confirmation"
    )
