from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools.workout_record import build_workout_record_tools
from nxtrep_backend.schemas.workout_record import WorkoutRecordDraftRequest
from nxtrep_backend.services.workout_record import WorkoutRecordService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,name,equipment",
    [
        ("史密斯上斜推胸", "杠铃卧推", "barbell"),
        ("上斜哑铃推胸", "上斜杠铃卧推", "barbell"),
        ("下斜杠铃卧推", "上斜杠铃卧推", "barbell"),
        ("平板哑铃卧推", "上斜哑铃卧推", "dumbbell"),
        ("绳索夹胸", "蝴蝶机夹胸", "machine"),
    ],
)
async def test_valid_id_cannot_override_explicit_exercise_variant(requested, name, equipment):
    exercise = SimpleNamespace(id=uuid4(), name_zh=name, equipment=equipment)
    workout = SimpleNamespace(
        repository=SimpleNamespace(get_exercise=AsyncMock(return_value=exercise))
    )
    confirmations = SimpleNamespace(add_confirmation=AsyncMock())
    service = WorkoutRecordService(workout, confirmations, SimpleNamespace())
    result = await service.propose_record(
        uuid4(),
        WorkoutRecordDraftRequest(
            exercise_id=exercise.id,
            exercise_name=requested,
            weight_kg=30,
            sets=4,
            reps=12,
        ),
    )
    assert result["status"] == "needs_review"
    assert result["error_code"] == "EXERCISE_VARIANT_MISMATCH"
    confirmations.add_confirmation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,name,equipment",
    [
        ("自由杠平板推胸", "杠铃卧推", "barbell"),
        ("卧推", "杠铃卧推", "barbell"),
        ("史密斯杠铃上斜推胸", "史密斯上斜推胸", "smith_machine"),
        ("上斜哑铃推胸", "上斜哑铃卧推", "dumbbell"),
    ],
)
async def test_non_conflicting_semantic_names_are_not_forced_to_exact_text(
    requested, name, equipment
):
    exercise = SimpleNamespace(id=uuid4(), name_zh=name, equipment=equipment)
    workout = SimpleNamespace(
        repository=SimpleNamespace(get_exercise=AsyncMock(return_value=exercise))
    )
    service = WorkoutRecordService(workout, SimpleNamespace(), SimpleNamespace())
    resolved = await service._resolve_exercise(
        uuid4(),
        WorkoutRecordDraftRequest(
            exercise_id=exercise.id,
            exercise_name=requested,
        ),
    )
    assert resolved is exercise


@pytest.mark.asyncio
async def test_tool_preserves_planned_name_and_date_when_executor_renames_them():
    service = SimpleNamespace(propose_record=AsyncMock(return_value={"status": "needs_review"}))
    context = SimpleNamespace(
        user_id=uuid4(),
        workout_record_service=service,
        task_scope={
            "_task_parameters": {"exercise_name": "史密斯上斜推胸", "workout_date": "2026-10-18"},
        },
    )
    propose = build_workout_record_tools(context)[0]
    arguments = {
        "request": {
            "exercise_name": "杠铃卧推",
            "exercise_id": str(uuid4()),
            "weight_kg": 30,
            "sets": 4,
            "reps": 12,
        }
    }
    await propose.ainvoke(arguments)
    body = service.propose_record.await_args.args[1]
    assert body.exercise_name == "史密斯上斜推胸"
    assert body.workout_date == date(2026, 10, 18)
    context.trace_context = {"conversation_id": str(uuid4())}
    await propose.ainvoke(arguments)
    assert (
        str(service.propose_record.await_args.kwargs["conversation_id"])
        == context.trace_context["conversation_id"]
    )
    service.propose_record.reset_mock()
    arguments["request"]["workout_date"] = "2026-10-17"
    result = await propose.ainvoke(arguments)
    assert result["error_code"] == "WORKOUT_TASK_DATE_MISMATCH"
    service.propose_record.assert_not_awaited()
