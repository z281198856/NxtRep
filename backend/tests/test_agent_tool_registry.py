import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext, build_tools, groups_for_task
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.workout import WorkoutNotFoundError

EXPECTED_TOOL_NAMES = {
    "read_water_entries",
    "propose_water_entry",
    "read_pending_business_draft",
    "propose_pending_draft_revision",
    "propose_workout_record",
    "read_workout_record_for_change",
    "propose_workout_record_update",
    "propose_workout_record_void",
    "propose_saved_meal_item_remove",
    "read_saved_meal_for_change",
    "propose_saved_meal_update",
    "propose_saved_meals_date_change",
    "propose_saved_meal_delete",
    "read_workout_set_for_change",
    "propose_workout_set_update",
    "propose_workout_set_void",
    "read_profile_for_update",
    "propose_profile_update",
    "propose_custom_food",
    "read_custom_food",
    "propose_custom_food_update",
    "propose_custom_food_delete",
    "read_profile_summary",
    "read_active_goal",
    "search_exercises",
    "read_exercise_detail",
    "read_active_training_plan",
    "read_calendar",
    "propose_training_plan",
    "propose_schedule_change",
    "read_recent_workouts",
    "read_active_workout",
    "read_workout_detail",
    "read_exercise_history",
    "propose_progression",
    "search_food_candidates",
    "read_nutrition_entries",
    "read_daily_nutrition_summary",
    "calculate_meal_option",
    "propose_nutrition_entry",
    "propose_nutrition_entry_from_reference",
    "propose_nutrition_entry_revision",
    "propose_nutrition_target",
    "read_body_progress",
    "read_personal_records",
    "calculate_navy_body_fat_range",
    "propose_body_measurement",
    "read_memories",
    "save_memory",
    "update_memory",
    "delete_memory",
    "read_confirmation_status",
    "list_confirmations",
    "cancel_confirmation",
    "retrieve_knowledge",
    "search_web",
    "read_progress_review",
    "read_recovery_status",
    "propose_recovery_adjustment",
}


def make_task(task_type: str, required_context: list[str] | None = None):
    return AgentIntentTask(
        task_type=task_type,
        required_context=required_context or [],
        confidence="high",
        routing_reason="test routing",
    )


def test_registry_builds_all_non_rag_tools_with_unique_names() -> None:
    context = MagicMock(spec=AgentToolContext)

    tools = build_tools(context)

    names = [item.name for item in tools]
    assert set(names) == EXPECTED_TOOL_NAMES
    assert len(names) == len(set(names))
    assert all("user_id" not in item.args for item in tools)


def test_general_question_only_receives_read_tools() -> None:
    groups = groups_for_task(make_task("general_question"))
    tools = build_tools(MagicMock(spec=AgentToolContext), groups=groups)
    names = {item.name for item in tools}

    assert "read_profile_summary" in names
    assert "search_exercises" in names
    assert "read_memories" in names
    assert "retrieve_knowledge" in names
    assert not any(name.startswith("propose_") for name in names)


def test_training_plan_task_receives_training_draft_tools() -> None:
    groups = groups_for_task(make_task("training_plan_draft"))
    names = {
        item.name
        for item in build_tools(
            MagicMock(spec=AgentToolContext),
            groups=groups,
        )
    }

    assert "propose_training_plan" in names
    assert "propose_schedule_change" in names
    assert "propose_progression" in names
    assert "propose_nutrition_entry" not in names


def test_required_context_can_only_add_whitelisted_read_group() -> None:
    groups = groups_for_task(
        make_task(
            "knowledge_retrieval",
            ["workout", "database", "nutrition_draft"],
        )
    )

    assert groups == frozenset({"knowledge", "web", "workout_read"})


def test_structured_query_with_known_context_only_receives_relevant_read_tools() -> None:
    groups = groups_for_task(
        make_task(
            "structured_data_query",
            ["training_plan", "calendar", "workout"],
        )
    )
    names = {
        item.name
        for item in build_tools(
            MagicMock(spec=AgentToolContext),
            groups=groups,
        )
    }

    assert groups == frozenset({"training_read", "workout_read"})
    assert "read_active_training_plan" in names
    assert "read_calendar" in names
    assert "read_active_workout" in names
    assert "read_daily_nutrition_summary" not in names


def test_memory_write_task_receives_only_direct_memory_capability() -> None:
    groups = groups_for_task(make_task("memory_write"))
    names = {
        item.name
        for item in build_tools(
            MagicMock(spec=AgentToolContext),
            groups=groups,
        )
    }

    assert "read_memories" in names
    assert "save_memory" in names
    assert "update_memory" in names
    assert "delete_memory" in names
    assert "read_confirmation_status" not in names
    assert "propose_training_plan" not in names


def test_registry_rejects_unknown_group() -> None:
    with pytest.raises(ValueError, match="Unknown Agent tool group"):
        build_tools(
            MagicMock(spec=AgentToolContext),
            groups=["admin"],  # type: ignore[list-item]
        )


def test_registry_keeps_stable_order_for_unordered_groups() -> None:
    context = MagicMock(spec=AgentToolContext)

    names = [
        item.name
        for item in build_tools(
            context,
            groups=frozenset({"workout_read", "profile"}),
        )
    ]

    assert names[:2] == ["read_profile_summary", "read_active_goal"]
    assert names[2] == "read_recent_workouts"


@pytest.mark.asyncio
async def test_tools_serialize_access_to_request_scoped_services() -> None:
    active_calls = 0
    maximum_active_calls = 0

    async def enter_operation(*_args, **_kwargs):
        nonlocal active_calls, maximum_active_calls
        active_calls += 1
        maximum_active_calls = max(maximum_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1

    training_service = MagicMock()
    training_service.get_active_plan = AsyncMock(side_effect=enter_operation)
    workout_service = MagicMock()

    async def missing_active_workout(*_args, **_kwargs):
        await enter_operation()
        raise WorkoutNotFoundError("No active workout")

    workout_service.get_active = AsyncMock(side_effect=missing_active_workout)
    context = AgentToolContext(
        user_id=uuid4(),
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=training_service,
        workout_service=workout_service,
        nutrition_service=MagicMock(),
        body_service=MagicMock(),
        confirmation_service=MagicMock(),
        memory_service=MagicMock(),
    )
    tools = {
        item.name: item
        for item in build_tools(
            context,
            groups={"training_read", "workout_read"},
        )
    }

    await asyncio.gather(
        tools["read_active_training_plan"].ainvoke({}),
        tools["read_active_workout"].ainvoke({}),
    )

    assert maximum_active_calls == 1
    assert {item["tool_name"] for item in context.tool_runs} == {
        "read_active_training_plan",
        "read_active_workout",
    }
    assert all(
        set(item)
        <= {
            "tool_name",
            "status",
            "duration_ms",
            "error_code",
            "tool_call_id",
            "argument_fingerprint",
            "replayed",
        }
        for item in context.tool_runs
    )
