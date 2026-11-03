import json
from dataclasses import replace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from langchain.tools import tool
from pydantic import ValidationError

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.agents.tools.registry import (
    TOOL_GROUP_BUILDERS,
    build_tools,
    safe_trace_snapshot,
)
from nxtrep_backend.schemas.workout_record import WorkoutRecordDraftRequest


def context(**kwargs):
    return AgentToolContext(
        user_id=uuid4(),
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=MagicMock(),
        workout_service=MagicMock(),
        nutrition_service=MagicMock(),
        body_service=MagicMock(),
        confirmation_service=MagicMock(),
        memory_service=MagicMock(),
        **kwargs,
    )


def registered(monkeypatch, builder, ctx):
    monkeypatch.setitem(TOOL_GROUP_BUILDERS, "review", builder)
    return {item.name: item for item in build_tools(ctx, groups={"review"})}


def confirmation():
    return {
        "status": "confirmation_required",
        "confirmation": {
            "confirmation_id": str(uuid4()),
            "operation_type": "nutrition_entry_update",
            "status": "pending",
            "version": 1,
        },
    }


@pytest.mark.asyncio
async def test_task_bound_target_blocks_different_or_missing_entity_before_business_call(
    monkeypatch,
):
    expected = uuid4()
    calls = []

    def builder(_ctx):
        @tool
        async def propose_saved_meal_delete(entry_id: UUID | None = None) -> dict:
            """Propose deleting one selected meal."""
            calls.append(entry_id)
            return confirmation()

        return [propose_saved_meal_delete]

    ctx = context(task_scope={"meal_id": str(expected)})
    command = registered(monkeypatch, builder, ctx)["propose_saved_meal_delete"]
    for args in ({"entry_id": str(uuid4())}, {}):
        blocked = await command.ainvoke(args)
        assert blocked["error_code"] == "TASK_ENTITY_CONFLICT"
    assert calls == []
    assert (await command.ainvoke({"entry_id": str(expected)}))["status"] == "confirmation_required"
    assert calls == [expected]


@pytest.mark.asyncio
async def test_preflight_runs_before_cached_result_replay_after_task_target_changes(monkeypatch):
    expected = uuid4()
    calls = []

    def builder(_ctx):
        @tool
        async def propose_saved_meal_update(entry_id: UUID) -> dict:
            """Propose a selected meal correction."""
            calls.append(entry_id)
            return confirmation()

        return [propose_saved_meal_update]

    ctx = context(task_scope={"entry_id": str(expected)})
    first = registered(monkeypatch, builder, ctx)["propose_saved_meal_update"]
    await first.ainvoke({"entry_id": str(expected)})
    other = replace(ctx, task_scope={"entry_id": str(uuid4())})
    rebuilt = registered(monkeypatch, builder, other)["propose_saved_meal_update"]
    assert (await rebuilt.ainvoke({"entry_id": str(expected)}))[
        "error_code"
    ] == "TASK_ENTITY_CONFLICT"
    assert calls == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_field", ["confirmation_id", "entry_id", "meal_id"])
async def test_bound_meal_cannot_create_a_second_independent_draft(monkeypatch, bound_field):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: int) -> dict:
            """Create a new meal draft."""
            calls.append(amount_g)
            return confirmation()

        return [propose_nutrition_entry]

    ctx = context(task_scope={bound_field: str(uuid4())})
    command = registered(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    result = await command.ainvoke({"amount_g": 200})

    assert result["status"] == "needs_review"
    assert result["error_code"] == "MEAL_REVISION_REQUIRED"
    assert result["required_tool"] == (
        "propose_nutrition_entry_revision"
        if bound_field == "confirmation_id"
        else "propose_saved_meal_update"
    )
    assert calls == []


@pytest.mark.asyncio
async def test_new_meal_scope_allows_creation_but_bound_scope_blocks_cached_replay(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry(amount_g: int) -> dict:
            """Create a new meal draft."""
            calls.append(amount_g)
            result = confirmation()
            result["confirmation"]["operation_type"] = "nutrition_entry_create"
            return result

        return [propose_nutrition_entry]

    ctx = context(task_scope={})
    command = registered(monkeypatch, builder, ctx)["propose_nutrition_entry"]
    created = await command.ainvoke({"amount_g": 200})
    assert created["status"] == "confirmation_required"
    assert calls == [200]

    bound = replace(ctx, task_scope={"confirmation_id": created["confirmation"]["confirmation_id"]})
    command = registered(monkeypatch, builder, bound)["propose_nutrition_entry"]
    assert (await command.ainvoke({"amount_g": 200}))["error_code"] == "MEAL_REVISION_REQUIRED"
    assert calls == [200]


@pytest.mark.asyncio
async def test_bound_meal_can_still_call_its_revision_tool(monkeypatch):
    selected = uuid4()
    calls = []

    def builder(_ctx):
        @tool
        async def propose_nutrition_entry_revision(confirmation_id: UUID) -> dict:
            """Revise one existing pending meal draft."""
            calls.append(confirmation_id)
            return confirmation()

        return [propose_nutrition_entry_revision]

    command = registered(
        monkeypatch, builder, context(task_scope={"confirmation_id": str(selected)})
    )["propose_nutrition_entry_revision"]
    result = await command.ainvoke({"confirmation_id": str(selected)})
    assert result["status"] == "confirmation_required"
    assert calls == [selected]


@pytest.mark.asyncio
async def test_bound_session_allows_new_exercise_id_but_not_another_workout(monkeypatch):
    session_id = uuid4()
    old_exercise = uuid4()
    calls = []

    def builder(_ctx):
        @tool
        async def propose_workout_record(request: WorkoutRecordDraftRequest) -> dict:
            """Append a newly specified action to a real session."""
            calls.append(request)
            return confirmation()

        return [propose_workout_record]

    ctx = context(
        task_scope={
            "session_id": str(session_id),
            "exercise_id": str(old_exercise),
            "workout_exercise_id": str(uuid4()),
        }
    )
    command = registered(monkeypatch, builder, ctx)["propose_workout_record"]
    args = {
        "request": {
            "workout_id": str(session_id),
            "exercise_id": str(uuid4()),
            "expected_workout_version": 9,
            "weight_kg": 25,
            "sets": 2,
            "reps": 10,
        }
    }
    assert (await command.ainvoke(args))["status"] == "confirmation_required"
    args["request"]["workout_id"] = str(uuid4())
    assert (await command.ainvoke(args))["error_code"] == "TASK_ENTITY_CONFLICT"
    assert len(calls) == 1 and calls[0].exercise_id != old_exercise


@pytest.mark.asyncio
async def test_read_can_resolve_other_entities_and_legacy_unbound_writes_remain_compatible(
    monkeypatch,
):
    calls = []

    def builder(_ctx):
        @tool
        async def read_workout_detail(workout_id: UUID) -> dict:
            """Read another workout before an explicit task switch."""
            calls.append(workout_id)
            return {"status": "available", "workout_id": str(workout_id)}

        return [read_workout_detail]

    other_id = uuid4()
    command = registered(monkeypatch, builder, context(task_scope={"workout_id": str(uuid4())}))[
        "read_workout_detail"
    ]
    assert (await command.ainvoke({"workout_id": str(other_id)}))["status"] == "available"
    assert calls == [other_id]


@pytest.mark.asyncio
async def test_schema_validation_still_precedes_gateway_and_business_execution(monkeypatch):
    calls = []

    def builder(_ctx):
        @tool
        async def cancel_confirmation(confirmation_id: UUID) -> dict:
            """Cancel a selected confirmation."""
            calls.append(confirmation_id)
            return {}

        return [cancel_confirmation]

    command = registered(
        monkeypatch, builder, context(task_scope={"confirmation_id": str(uuid4())})
    )["cancel_confirmation"]
    with pytest.raises(ValidationError):
        await command.ainvoke({"confirmation_id": "刚才那个"})
    assert calls == []


@pytest.mark.asyncio
async def test_trace_links_tool_to_turn_and_sanitizes_argument_result_snapshots(monkeypatch):
    conversation_id, turn_id, task_id, trace_id = [uuid4() for _ in range(4)]
    secret = "sk-not-a-real-credential-1234567890"

    def builder(_ctx):
        @tool
        async def propose_custom_food(name: str, amount_g: int, notes: str) -> dict:
            """Create a draft with traceable structured food facts."""
            return {
                **confirmation(),
                "draft": {"name": name, "amount_g": amount_g, "notes": notes, "api_key": secret},
            }

        return [propose_custom_food]

    ctx = context(
        task_id=task_id,
        trace_context={
            "conversation_id": str(conversation_id),
            "turn_id": str(turn_id),
            "trace_id": str(trace_id),
        },
    )
    command = registered(monkeypatch, builder, ctx)["propose_custom_food"]
    await command.ainvoke({"name": "鸡腿饭", "amount_g": 200, "notes": secret})
    trace = ctx.journal.snapshot()["tool_runs"][0]
    assert {key: trace[key] for key in ("conversation_id", "turn_id", "task_id", "trace_id")} == {
        "conversation_id": str(conversation_id),
        "turn_id": str(turn_id),
        "task_id": str(task_id),
        "trace_id": str(trace_id),
    }
    assert UUID(trace["tool_call_id"]) and trace["tool_call_id_source"] == "gateway"
    assert trace["arguments_snapshot"]["amount_g"] == 200
    assert trace["result_snapshot"]["draft"]["name"] == "鸡腿饭"
    assert secret not in json.dumps(trace, ensure_ascii=False)


def test_trace_snapshots_are_bounded_and_redact_nested_credential_text():
    snapshot = safe_trace_snapshot(
        {
            "rows": [{"name": "Bearer abcdef-secret", "x": "z" * 9000}] * 500,
            "authorization": "never-copy",
            "notes": "private prose",
        }
    )
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert len(serialized) <= 4096
    assert "abcdef-secret" not in serialized and "never-copy" not in serialized
    assert "private prose" not in serialized
