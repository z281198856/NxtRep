from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.agents.tools.workout_record import build_workout_record_tools
from nxtrep_backend.schemas.workout_record import (
    WorkoutRecordDraftRequest,
    WorkoutRecordUpdateRequest,
)
from nxtrep_backend.services.workout_record import WorkoutRecordService


@pytest.mark.parametrize("changes", [{}, {"weight_kg": None}, {"reps": None}, {"weight_kg": -1}])
def test_workout_record_correction_requires_real_valid_change(changes):
    with pytest.raises(ValidationError):
        WorkoutRecordUpdateRequest(
            expected_workout_version=1,
            set_versions=[{"set_id": uuid4(), "expected_version": 1}],
            reason="更正",
            **changes,
        )


@pytest.mark.asyncio
async def test_incomplete_workout_record_does_not_create_confirmation_or_business_data():
    workout = SimpleNamespace(repository=SimpleNamespace(get_active=AsyncMock()))
    confirmations = SimpleNamespace(add_confirmation=AsyncMock())
    service = WorkoutRecordService(workout, confirmations, SimpleNamespace())
    result = await service.propose_record(uuid4(), WorkoutRecordDraftRequest(exercise_name="卧推"))
    assert result["status"] == "needs_review"
    assert result["missing_fields"] == ["weight_kg", "sets", "reps"]
    workout.repository.get_active.assert_not_awaited()
    confirmations.add_confirmation.assert_not_awaited()


@pytest.mark.asyncio
async def test_workout_record_tools_read_unique_current_versions_before_batch_change(monkeypatch):
    workout_id, item_id, set_id = uuid4(), uuid4(), uuid4()
    versions = [{"set_id": str(set_id), "expected_version": 1}]
    service = SimpleNamespace(
        read_for_change=AsyncMock(
            return_value={
                "status": "available",
                "selected_record": {
                    "workout_id": str(workout_id),
                    "workout_exercise_id": str(item_id),
                    "expected_workout_version": 7,
                    "set_versions": versions,
                },
            }
        ),
        propose_change=AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "nxtrep_backend.agents.tools.workout_record.confirmation_payload",
        lambda _: {"operation_type": "workout_record_update"},
    )
    tools = build_workout_record_tools(
        SimpleNamespace(user_id=uuid4(), workout_record_service=service)
    )
    read, update = tools[1:3]
    args = {
        "workout_id": str(workout_id),
        "workout_exercise_id": str(item_id),
        "request": {
            "expected_workout_version": 7,
            "set_versions": versions,
            "reason": "更正",
            "weight_kg": 55,
        },
    }
    assert (await update.ainvoke(args))["status"] == "needs_review"
    service.propose_change.assert_not_awaited()
    await read.ainvoke({"workout_id": str(workout_id), "workout_exercise_id": str(item_id)})
    assert (await update.ainvoke(args))["status"] == "confirmation_required"
    service.propose_change.assert_awaited_once()
    args["request"]["expected_workout_version"] = 6
    assert (await update.ainvoke(args))["status"] == "needs_review"
    assert service.propose_change.await_count == 1


def test_unconfigured_workout_record_service_exposes_no_new_tools():
    assert build_workout_record_tools(SimpleNamespace()) == []
