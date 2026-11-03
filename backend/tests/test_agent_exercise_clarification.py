"""Exercise names can need a choice without losing the supplied workout data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from test_agent_multiturn_pipeline import Pipeline, card, make_graph, route_to, tool_context

from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext


def review(names=("杠铃卧推", "上斜哑铃卧推", "哑铃地板卧推", "哑铃平板卧推")):
    return {
        "status": "needs_review", "missing_fields": ["exercise_id"],
        "message": "找到多个可能的动作，请选择具体动作。",
        "candidates": [{"exercise_id": str(uuid4()), "exercise_name": name} for name in names],
    }


def ready_state():
    return TaskStateManager.apply_plan({}, "workout_record_draft", {"parameters": {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
        "workout_date": "2026-10-17",
    }})


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["杠铃", "杠铃的", "就选杠铃", "杠铃卧推", "第一个"])
async def test_exercise_choice_preserves_same_task_and_calls_tool_with_real_id(reply):
    choices = review()
    router = SimpleNamespace(route=AsyncMock(return_value=route_to("workout_record_draft", {
        "exercise_name": "卧推", "weight_kg": 55, "sets": 4, "reps": 8,
    })))
    service = SimpleNamespace(propose_record=AsyncMock(side_effect=[
        choices, card("workout_record_create"),
    ]))
    ctx = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, ctx), ctx.user_id)
    first = await pipeline.turn("卧推55kg4组每组8次")
    task_id = pipeline.task.task_id
    assert first["execution_bundle"].branch_results[0].status == "needs_input"
    assert all(item["exercise_name"] in first["response_message"] for item in choices["candidates"])
    assert len(pipeline.task.candidates) == 4
    assert pipeline.task.missing_fields == ["selection"]
    assert service.propose_record.await_count == 1

    final = await pipeline.turn(reply)
    assert pipeline.task.task_id == task_id and pipeline.task.status == "awaiting_confirmation"
    assert len(final["execution_bundle"].branch_results[0].confirmation_cards) == 1
    actual = service.propose_record.call_args.args[1]
    assert actual.exercise_id == UUID(choices["candidates"][0]["exercise_id"])
    assert actual.exercise_name == "杠铃卧推"
    assert actual.weight_kg == 55 and actual.sets == 4 and actual.reps == 8
    router.route.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("result_status,step", [
    ("needs_review", "clarify_target"), ("needs_input", "collect_parameters"),
])
async def test_legacy_exercise_review_can_continue_without_repeating_workout_details(
    result_status, step,
):
    choices = review()
    choices["status"] = result_status
    state = ready_state()
    active = state.active_task
    task_id = active.task_id
    # Exact shape of the observed App turn: raw candidates persisted, adapter dropped them.
    active.status, active.current_step = "collecting", step
    active.last_tool_result, active.missing_fields = choices, ["exercise_id"]
    active.candidates = []
    original = state.model_dump(mode="json")
    router = SimpleNamespace(route=AsyncMock())
    service = SimpleNamespace(propose_record=AsyncMock(return_value=card("workout_record_create")))
    ctx = tool_context(workout_record_service=service)
    pipeline = Pipeline(
        make_graph(router, ctx), ctx.user_id, AgentConversationContext(task_state=original),
    )
    result = await pipeline.turn("杠铃的")
    assert result["execution_bundle"].branch_results[0].status == "completed"
    assert pipeline.task.task_id == task_id
    assert service.propose_record.call_args.args[1].weight_kg == 55
    assert original["active_task"]["candidates"] == [], "Loading must not mutate caller data"
    router.route.assert_not_awaited()


@pytest.mark.asyncio
async def test_semantic_exercise_selection_accepts_verified_candidate_id_only():
    choices = review()
    state = TaskStateManager.commit_results(ready_state(), [choices])
    state.active_task.missing_fields = ["selection"]
    selected_id = choices["candidates"][0]["exercise_id"]
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(
        "workout_record_draft", parameters={"exercise_name": "杠铃卧推"},
        entities={"exercise_id": selected_id}, transition="continue",
    )))
    service = SimpleNamespace(propose_record=AsyncMock(return_value=card("workout_record_create")))
    ctx = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, ctx), ctx.user_id, AgentConversationContext(
        task_state=state.model_dump(mode="json"),
    ))
    result = await pipeline.turn("我是躺在平凳上推长杆的那种")
    assert result["execution_bundle"].branch_results[0].status == "completed"
    assert pipeline.task.task_id == state.active_task.task_id
    actual = service.propose_record.call_args.args[1]
    assert actual.exercise_id == UUID(selected_id) and actual.weight_kg == 55
    assert actual.exercise_name == "杠铃卧推" and actual.sets == 4 and actual.reps == 8

    # A model-proposed ID outside the verified choices remains untrusted.
    router.route.return_value = route_to(
        "workout_record_draft", entities={"exercise_id": str(uuid4())}, transition="continue",
    )
    service.propose_record.reset_mock()
    pipeline.context = AgentConversationContext(task_state=state.model_dump(mode="json"))
    result = await pipeline.turn("我是用另外那个动作")
    assert result["execution_bundle"].branch_results[0].status == "needs_input"
    service.propose_record.assert_not_awaited()


@pytest.mark.parametrize("reply", ["哑铃", "就选哑铃"])
def test_shared_equipment_name_does_not_guess_one_of_several_exercises(reply):
    state = TaskStateManager.commit_results(ready_state(), [review()])
    state.active_task.missing_fields = ["selection"]
    prepared = TaskStateManager.prepare_turn(state, reply)
    assert prepared.handled and prepared.clarification_required
    assert prepared.selection is None and not prepared.entities
    assert prepared.state.active_task.parameters["weight_kg"] == "55"


@pytest.mark.parametrize("message", [
    "杠铃和哑铃有什么区别？", "为什么选杠铃", "不是杠铃", "杠铃先别记，先查昨天的训练",
])
def test_exercise_question_negation_or_additional_request_is_not_a_selection(message):
    state = TaskStateManager.commit_results(ready_state(), [review()])
    state.active_task.missing_fields = ["selection"]
    prepared = TaskStateManager.prepare_turn(state, message)
    assert not prepared.handled and not prepared.parameters
    assert prepared.selection is None
    assert not prepared.state.active_task.entities


@pytest.mark.asyncio
async def test_other_ambiguous_exercise_follows_same_path_without_bench_press_special_case():
    choices = review(("杠铃划船", "哑铃划船"))
    router = SimpleNamespace(route=AsyncMock(return_value=route_to("workout_record_draft", {
        "exercise_name": "划船", "weight_kg": 20, "sets": 3, "reps": 12,
    })))
    service = SimpleNamespace(propose_record=AsyncMock(side_effect=[
        choices, card("workout_record_create"),
    ]))
    ctx = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, ctx), ctx.user_id)
    await pipeline.turn("划船20kg3组12次")
    await pipeline.turn("第二个")
    actual = service.propose_record.call_args.args[1]
    assert actual.exercise_id == UUID(choices["candidates"][1]["exercise_id"])
    assert actual.exercise_name == "哑铃划船"
    assert actual.weight_kg == 20 and actual.sets == 3 and actual.reps == 12


def test_workout_review_also_keeps_real_session_candidate():
    identifier = str(uuid4())
    state = TaskStateManager.commit_results(ready_state(), [{
        "status": "needs_review", "missing_fields": ["workout_id"],
        "candidates": [{"workout_id": identifier, "date": "2026-10-17"}],
    }])
    assert state.active_task.candidates[0].kind == "workout"
    prepared = TaskStateManager.prepare_turn(state, "第一个")
    assert prepared.entities["workout_id"] == identifier
