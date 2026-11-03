"""Regressions for the observed add-versus-replace failure and related task gaps."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext, build_tools
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.schemas.nutrition import NutritionPendingEntryRevisionRequest
from nxtrep_backend.services.agent_errors import public_agent_error
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_task_state import AgentTaskCapacityError, TaskStateManager
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionService


def food(name, amount="150", kcal="225"):
    return {
        "name": name,
        "amount_g": amount,
        "basis_amount_g": amount,
        "kcal": kcal,
        "protein_g": "18",
        "carbs_g": "2",
        "fat_g": "16",
        "source": "model_estimated",
        "confidence": "low",
        "estimate_assumptions": "按常见份量估算，未核验",
    }


def card(operation="nutrition_entry_create", after=None):
    return SimpleNamespace(
        id=uuid4(),
        operation_type=operation,
        status="pending",
        before=None,
        after=after or {},
        version=1,
        impact="确认后生效",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def context(**overrides):
    data = {
        k: MagicMock()
        for k in (
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
    }
    data.update(user_id=uuid4(), task_id=uuid4())
    data.update(overrides)
    return AgentToolContext(**data)


def reference_tools(parameters):
    source = SimpleNamespace(
        id=uuid4(), version=1, items=[food("鸡腿肉"), food("空心菜"), food("米饭", "190", "247")]
    )
    service = SimpleNamespace(
        get_saved_entry=AsyncMock(return_value=source), propose_entry=AsyncMock(return_value=card())
    )
    ctx = context(
        nutrition_service=service,
        task_scope={
            "_reference_entities": {"entry_id": str(source.id)},
            "_task_parameters": parameters,
        },
    )
    tools = {t.name: t for t in build_tools(ctx, groups={"nutrition_draft"})}
    args = {
        "source_entry_id": str(source.id),
        "expected_source_version": 1,
        "meal_type": "dinner",
        "eaten_at": "2026-10-13T19:00:00+08:00",
        "replacements": [],
        "notes": "参考前一餐",
    }
    return tools, service, source, args


@pytest.mark.asyncio
async def test_add_egg_keeps_every_original_food_and_repeated_call_reuses_card():
    tools, service, source, args = reference_tools({"additions": [{"food_name": "肉沫蒸蛋"}]})
    original = deepcopy(source.items)
    args["additions"] = [food("肉沫蒸蛋", "200", "230")]
    first = await tools["propose_nutrition_entry_from_reference"].ainvoke(args)
    second = await tools["propose_nutrition_entry_from_reference"].ainvoke(args)
    assert first["status"] == "confirmation_required"
    assert second["confirmation"]["confirmation_id"] == first["confirmation"]["confirmation_id"]
    service.propose_entry.assert_awaited_once()
    items = service.propose_entry.call_args.kwargs["body"].items
    assert [f.name for f in items] == ["鸡腿肉", "空心菜", "米饭", "肉沫蒸蛋"]
    assert [f.model_dump(mode="json", exclude_none=True) for f in items[:3]] == original
    assert source.items == original
    assert first["applied_operations"]["result_item_count"] == 4


@pytest.mark.asyncio
async def test_retry_cannot_turn_addition_into_replacement_or_generic_recreation():
    tools, service, _, args = reference_tools({"additions": [{"food_name": "肉沫蒸蛋"}]})
    for index in (3, 2):
        result = await tools["propose_nutrition_entry_from_reference"].ainvoke(
            {**args, "replacements": [{**food("肉沫蒸蛋"), "item_index": index}]}
        )
        assert result["error_code"] == "MEAL_ACTION_MISMATCH"
    bypass = await tools["propose_nutrition_entry"].ainvoke(
        {"meal_type": "dinner", "eaten_at": args["eaten_at"], "items": [food("肉沫蒸蛋")]}
    )
    assert bypass["error_code"] == "REFERENCE_TOOL_REQUIRED"
    service.propose_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_reference_changes_keep_original_indices_and_unmentioned_food():
    tools, service, _, args = reference_tools(
        {
            "additions": [{"food_name": "酸奶"}],
            "replacements": [{"from": "空心菜", "to": "西兰花"}],
            "removals": ["米饭"],
        }
    )
    result = await tools["propose_nutrition_entry_from_reference"].ainvoke(
        {
            **args,
            "additions": [food("酸奶")],
            "remove_item_indices": [2],
            "replacements": [{**food("西兰花"), "item_index": 1}],
        }
    )
    assert result["status"] == "confirmation_required"
    assert [item.name for item in service.propose_entry.call_args.kwargs["body"].items] == [
        "鸡腿肉",
        "西兰花",
        "酸奶",
    ]


@pytest.mark.asyncio
async def test_copy_without_changes_cannot_introduce_an_unrequested_replacement():
    tools, service, _, args = reference_tools({"reference_meal_type": "dinner"})
    result = await tools["propose_nutrition_entry_from_reference"].ainvoke(
        {
            **args,
            "replacements": [{**food("蒸蛋"), "item_index": 2}],
        }
    )
    assert result["error_code"] == "MEAL_ACTION_MISMATCH"
    service.propose_entry.assert_not_awaited()
    result = await tools["propose_nutrition_entry_from_reference"].ainvoke(args)
    assert result["status"] == "confirmation_required"
    assert [item.name for item in service.propose_entry.call_args.kwargs["body"].items] == [
        "鸡腿肉",
        "空心菜",
        "米饭",
    ]


def pending_service(item):
    original = card(
        after={
            "entry": {
                "meal_type": "lunch",
                "eaten_at": "2026-10-16T12:00:00+08:00",
                "items": [item],
            }
        }
    )
    service = NutritionService(
        SimpleNamespace(session=SimpleNamespace(flush=AsyncMock())),
        SimpleNamespace(get_confirmation=AsyncMock(return_value=original)),
    )
    service.propose_entry = AsyncMock(return_value=card())
    return service, original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item", [food("虾仁滑蛋"), {"food_version_id": str(uuid4()), "name": "米饭", "amount_g": "200"}]
)
async def test_name_only_cannot_masquerade_as_replacement_or_invalidate_old_card(item):
    service, old = pending_service(item)
    with pytest.raises(NutritionConflictError, match="replacement"):
        await service.revise_pending_entry(
            uuid4(),
            old.id,
            NutritionPendingEntryRevisionRequest(
                expected_version=1, changes=[{"item_index": 0, "name": "空心菜"}]
            ),
        )
    assert old.status == "pending" and old.version == 1
    service.propose_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_replacement_changes_food_basis_and_pending_addition_is_separate():
    service, old = pending_service(food("虾仁滑蛋"))
    await service.revise_pending_entry(
        uuid4(),
        old.id,
        NutritionPendingEntryRevisionRequest(
            expected_version=1,
            changes=[{"item_index": 0, "replacement": food("空心菜", kcal="110")}],
            additions=[food("蒸蛋")],
        ),
    )
    items = service.propose_entry.call_args.kwargs["body"].items
    assert [(item.name, int(item.kcal)) for item in items] == [("空心菜", 110), ("蒸蛋", 225)]
    assert old.status == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [True, False])
async def test_food_scope_and_read_selection_block_a_different_item(bound):
    entry = SimpleNamespace(
        id=uuid4(),
        version=1,
        meal_type="lunch",
        eaten_at=datetime.now(UTC),
        items=[food("米饭"), food("鸡胸肉")],
        totals={},
        notes=None,
    )
    service = SimpleNamespace(
        get_saved_entry=AsyncMock(return_value=entry),
        propose_saved_entry_change=AsyncMock(return_value=card("nutrition_entry_update")),
    )
    ctx = context(
        nutrition_service=service,
        task_scope={"entry_id": str(entry.id), "item_index": 1} if bound else {},
    )
    tools = {t.name: t for t in build_tools(ctx, groups={"nutrition_changes"})}
    await tools["read_saved_meal_for_change"].ainvoke(
        {"entry_id": str(entry.id), "food_name": "鸡胸肉"}
    )
    result = await tools["propose_saved_meal_update"].ainvoke(
        {
            "entry_id": str(entry.id),
            "request": {
                "expected_version": 1,
                "reason": "更正",
                "changes": [{"item_index": 0, "amount_g": 250}],
            },
        }
    )
    assert result["error_code"] == ("TASK_ITEM_CONFLICT" if bound else "READ_ITEM_CONFLICT")
    service.propose_saved_entry_change.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("repeated_date", [None, "2026-10-17", "2026-10-16"])
async def test_workout_set_count_reaches_existing_tool_without_being_discarded(
    mixed, repeated_date
):
    workout_id, exercise_id = uuid4(), uuid4()
    selected = {
        "date": "2026-10-17",
        "workout_id": str(workout_id),
        "workout_exercise_id": str(exercise_id),
        "expected_workout_version": 1,
        "set_versions": [{"set_id": str(uuid4()), "expected_version": 1} for _ in range(4)],
    }
    service = SimpleNamespace(
        read_for_change=AsyncMock(
            return_value={"status": "available", "selected_record": selected}
        ),
        propose_change=AsyncMock(return_value=card("workout_record_update")),
    )
    ctx = context(workout_record_service=service)
    parameters = {"sets": 3, "_changed_fields": ["sets"]}
    if mixed:
        parameters.update(weight_kg=55, _changed_fields=["weight_kg", "sets"])
    if repeated_date:
        parameters["workout_date"] = repeated_date
        parameters["_changed_fields"].append("workout_date")
    task = AgentIntentTask(
        task_type="workout_record_update_draft",
        task_id=uuid4(),
        confidence="high",
        routing_reason="更正组数",
        task_update=AgentTaskUpdate(
            transition="correct",
            parameters=parameters,
            entities={"workout_id": str(workout_id), "workout_exercise_id": str(exercise_id)},
        ),
    )
    result = await TaskActionHandler(ctx).execute(
        AgentBranchInput(user_id=ctx.user_id, message="改成三组", task=task, images=())
    )
    if repeated_date and repeated_date != selected["date"]:
        assert result.status == "needs_input" and not result.requires_confirmation
        service.propose_change.assert_not_awaited()
        return
    assert result.requires_confirmation
    body = service.propose_change.call_args.args[3]
    assert body.sets == 3 and (not mixed or body.weight_kg == 55)


def interrupted():
    state = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {"transition": "new", "parameters": {"exercise_name": "卧推", "weight_kg": 60}},
    )
    identifier = state.active_task.task_id
    state = TaskStateManager.apply_plan(
        state, "nutrition_record_draft", {"transition": "new", "parameters": {"meal_type": "lunch"}}
    )
    state = TaskStateManager.apply_plan(state, "training_plan_draft", {"transition": "new"})
    return state, identifier


def test_second_interruption_and_json_roundtrip_preserve_original_task():
    state, identifier = interrupted()
    state = TaskStateManager.load(state.model_dump(mode="json"))
    resumed = TaskStateManager.apply_plan(
        state, "workout_record_draft", {"transition": "resume", "resume_task_id": str(identifier)}
    )
    assert resumed.active_task.task_id == identifier
    assert resumed.active_task.parameters["weight_kg"] == "60"
    assert resumed.active_task.missing_fields == ["sets", "reps"]
    assert {t.task_type for t in (resumed.suspended_task, *resumed.suspended_tasks)} == {
        "nutrition_record_draft",
        "training_plan_draft",
    }


def test_grounded_correction_can_restore_an_earlier_paused_task_directly():
    state, identifier = interrupted()
    old = next(t for t in TaskStateManager.tasks(state) if t.task_id == identifier)
    workout_id = str(uuid4())
    old.entities["workout_id"] = workout_id
    restored = TaskStateManager.apply_plan(
        state,
        "workout_record_update_draft",
        {
            "transition": "correct",
            "entities": {"workout_id": workout_id},
            "parameters": {"weight_kg": 55},
        },
    )
    assert restored.active_task.task_id == identifier
    assert restored.active_task.parameters["weight_kg"] == "55"
    assert len(restored.suspended_tasks) == 1


def test_ambiguous_or_invented_resume_target_requires_selection():
    state, _ = interrupted()
    assert not TaskStateManager.prepare_turn(state, "继续刚才的任务").handled
    resumed = TaskStateManager.apply_plan(
        state, "workout_record_draft", {"transition": "resume", "resume_task_id": str(uuid4())}
    )
    assert resumed.active_task.missing_fields == ["selection"]


def test_multiple_paused_tasks_do_not_resume_the_completed_active_task_by_shortcut():
    state, _ = interrupted()
    state.active_task.status = "completed"
    assert not TaskStateManager.prepare_turn(state, "继续刚才的训练").handled


def test_paused_task_limit_never_discards_existing_parameters_or_retries_blindly():
    state = {}
    for index in range(6):
        state = TaskStateManager.apply_plan(
            state,
            "training_plan_draft",
            {
                "transition": "new",
                "parameters": {"name": f"训练任务{index}"},
            },
        )
    snapshot = state.model_dump(mode="json")
    with pytest.raises(AgentTaskCapacityError) as failure:
        TaskStateManager.apply_plan(state, "nutrition_record_draft", {"transition": "new"})
    assert state.model_dump(mode="json") == snapshot
    error = public_agent_error(failure.value)
    assert error.code == "TASK_CAPACITY_LIMIT" and not error.retryable
    assert "五个暂停任务" in error.message


def test_explicit_different_date_drops_even_repeated_old_session_id():
    workout_id = str(uuid4())
    state = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {
            "transition": "new",
            "entities": {"workout_id": workout_id},
            "parameters": {
                "exercise_name": "卧推",
                "workout_date": "2026-10-16",
                "weight_kg": 60,
                "sets": 4,
                "reps": 8,
            },
        },
    )
    changed = TaskStateManager.apply_plan(
        state,
        "workout_record_draft",
        {
            "transition": "new",
            "entities": {"workout_id": workout_id},
            "parameters": {"exercise_name": "上斜卧推", "workout_date": "2026-10-15"},
        },
    )
    assert "workout_id" not in changed.active_task.entities
    assert "weight_kg" not in changed.active_task.parameters
    assert changed.active_task.parameters["workout_date"] == "2026-10-15"
