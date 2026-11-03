from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.agents.runtime import build_agent
from nxtrep_backend.agents.tools import AgentToolContext, groups_for_task
from nxtrep_backend.agents.tools.workout import build_workout_correction_tools
from nxtrep_backend.core.config import Settings
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.workout import WorkoutSetCorrectionRequest


@pytest.mark.parametrize(
    "changes", [{}, {"weight_kg": None}, {"reps": None}, {"weight_kg": -1}, {"reps": 1001}]
)
def test_set_correction_rejects_empty_and_invalid_values(changes):
    with pytest.raises(ValidationError):
        WorkoutSetCorrectionRequest(expected_version=1, reason="更正", **changes)


@pytest.mark.parametrize(
    "task_type,permitted",
    [
        ("workout_set_update_draft", "propose_workout_set_update"),
        ("workout_set_void_draft", "propose_workout_set_void"),
    ],
)
def test_workout_correction_runtime_exposes_only_authorized_action(
    task_type, permitted, monkeypatch
):
    task = AgentIntentTask(task_type=task_type, confidence="high", routing_reason="test")
    captured = {}
    monkeypatch.setattr(
        "nxtrep_backend.agents.runtime.create_agent", lambda **kwargs: captured.update(kwargs)
    )
    build_agent(
        Settings(),
        tool_context=MagicMock(spec=AgentToolContext),
        model=MagicMock(),
        tool_groups=groups_for_task(task),
        task_type=task.task_type,
    )
    names = {t.name for t in captured["tools"]}
    assert {name for name in names if name.startswith("propose_")} == {permitted}
    assert "read_workout_set_for_change" in names and "save_memory" not in names


def context_with_sets(ambiguous=False):
    workout_id, exercise_id, set_id = uuid4(), uuid4(), uuid4()
    item = SimpleNamespace(id=set_id, version=1, set_index=2, weight_kg=50, reps=10)
    workout = SimpleNamespace(id=workout_id, started_at=datetime.now(UTC))
    exercise = SimpleNamespace(id=exercise_id, name_snapshot="卧推")
    aggregate = SimpleNamespace(
        workout=workout, exercises=[exercise], sets_by_exercise={exercise_id: [item]}
    )
    if ambiguous:
        other = SimpleNamespace(id=uuid4(), name_snapshot="卧推")
        aggregate.exercises.append(other)
        aggregate.sets_by_exercise[other.id] = [
            SimpleNamespace(id=uuid4(), version=1, set_index=2, weight_kg=40, reps=8)
        ]
    service = SimpleNamespace(
        get_aggregate=AsyncMock(return_value=aggregate),
        propose_set_change=AsyncMock(return_value=object()),
    )
    return SimpleNamespace(user_id=uuid4(), workout_service=service), workout_id, set_id


@pytest.mark.asyncio
async def test_workout_set_requires_read_and_deduplicates_same_proposal(monkeypatch):
    context, workout_id, set_id = context_with_sets()
    monkeypatch.setattr(
        "nxtrep_backend.agents.tools.workout.confirmation_payload",
        lambda _: {"operation_type": "workout_set_update"},
    )
    read, propose, _ = build_workout_correction_tools(context)
    body = {
        "workout_id": str(workout_id),
        "set_id": str(set_id),
        "changes": {"reps": 8, "expected_version": 1, "reason": "更正"},
    }
    assert (await propose.ainvoke(body))["status"] == "needs_review"
    context.workout_service.propose_set_change.assert_not_awaited()
    selected = await read.ainvoke(
        {"workout_id": str(workout_id), "exercise_name": "卧推", "set_index": 2}
    )
    assert selected["selected_set"]["set_id"] == str(set_id)
    assert (await propose.ainvoke(body))["status"] == "confirmation_required"
    await propose.ainvoke(body)
    context.workout_service.propose_set_change.assert_awaited_once()
    assert context.workout_service.propose_set_change.await_args.args[3].model_fields_set == {
        "reps",
        "expected_version",
        "reason",
    }


@pytest.mark.asyncio
async def test_ambiguous_set_and_missing_date_do_not_enable_changes():
    context, workout_id, set_id = context_with_sets(ambiguous=True)
    read, _, void = build_workout_correction_tools(context)
    assert (await read.ainvoke({"exercise_name": "卧推", "set_index": 2}))[
        "status"
    ] == "needs_review"
    result = await read.ainvoke(
        {"exercise_name": "卧推", "set_index": 2, "workout_id": str(workout_id)}
    )
    assert result["status"] == "needs_review" and len(result["candidates"]) == 2
    assert (
        await void.ainvoke(
            {
                "workout_id": str(workout_id),
                "set_id": str(set_id),
                "request": {"expected_version": 1, "reason": "误记"},
            }
        )
    )["status"] == "needs_review"
    context.workout_service.propose_set_change.assert_not_awaited()
