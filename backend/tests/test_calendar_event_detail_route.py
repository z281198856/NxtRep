from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.routes import calendar


@pytest.mark.asyncio
async def test_detail_resolves_visible_names_and_preserves_saved_snapshot(monkeypatch):
    user_id, event_id, exercise_id, unavailable_id, named_id = (uuid4() for _ in range(5))
    snapshot = {
        "name": "历史胸部训练",
        "exercises": [
            {"exercise_id": str(exercise_id), "target_sets": 4},
            {"exercise_id": str(unavailable_id), "target_sets": 3},
            {"exercise_id": str(named_id), "exercise_name": "快照里的原名称"},
        ],
    }
    original = deepcopy(snapshot)
    item = SimpleNamespace(
        id=event_id,
        scheduled_date=date(2024, 2, 29),
        status="missed",
        plan_day_id=uuid4(),
        title="历史胸部训练",
        estimated_minutes=45,
        actual_workout_id=None,
        plan_version_id=uuid4(),
        content_snapshot=snapshot,
    )
    repository = SimpleNamespace(
        get_calendar_event=AsyncMock(return_value=item),
        plan_exercise_names=AsyncMock(return_value={str(exercise_id): "杠铃卧推"}),
    )
    monkeypatch.setattr(calendar, "SqlAlchemyTrainingRepository", lambda _: repository)

    response = await calendar.get_calendar_event(event_id, SimpleNamespace(id=user_id), object())

    repository.get_calendar_event.assert_awaited_once_with(user_id, event_id)
    repository.plan_exercise_names.assert_awaited_once_with(user_id, {exercise_id, unavailable_id})
    assert [exercise["exercise_name"] for exercise in response.content_snapshot["exercises"]] == [
        "杠铃卧推",
        "动作已不可用",
        "快照里的原名称",
    ]
    assert response.content_snapshot["exercises"][0]["target_sets"] == 4
    assert snapshot == original


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [None, {"exercises": []}])
async def test_detail_without_exercises_does_not_query_other_plans(monkeypatch, snapshot):
    event_id, user_id = uuid4(), uuid4()
    item = SimpleNamespace(
        id=event_id,
        scheduled_date=date(2024, 2, 29),
        status="planned",
        plan_day_id=None,
        title="散步",
        estimated_minutes=30,
        actual_workout_id=None,
        plan_version_id=None,
        content_snapshot=snapshot,
    )
    repository = SimpleNamespace(
        get_calendar_event=AsyncMock(return_value=item), plan_exercise_names=AsyncMock()
    )
    monkeypatch.setattr(calendar, "SqlAlchemyTrainingRepository", lambda _: repository)
    response = await calendar.get_calendar_event(event_id, SimpleNamespace(id=user_id), object())
    assert response.content_snapshot == snapshot
    repository.plan_exercise_names.assert_not_awaited()


@pytest.mark.asyncio
async def test_inaccessible_event_does_not_resolve_any_exercise(monkeypatch):
    repository = SimpleNamespace(
        get_calendar_event=AsyncMock(return_value=None), plan_exercise_names=AsyncMock()
    )
    monkeypatch.setattr(calendar, "SqlAlchemyTrainingRepository", lambda _: repository)
    with pytest.raises(ApiError) as error:
        await calendar.get_calendar_event(uuid4(), SimpleNamespace(id=uuid4()), object())
    assert error.value.code == "CALENDAR_EVENT_NOT_FOUND"
    repository.plan_exercise_names.assert_not_awaited()
