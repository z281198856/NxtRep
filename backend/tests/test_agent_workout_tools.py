from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.workout import build_workout_read_tools
from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.schemas.workout import (
    WorkoutHistoryItem,
    WorkoutHistoryResponse,
)
from nxtrep_backend.services.workout import WorkoutService


def make_workout_service() -> MagicMock:
    service = MagicMock(spec=WorkoutService)
    service.list_history = AsyncMock()
    service.list_exercise_history = AsyncMock()
    return service


def build_workout_tool(
    *,
    user_id,
    workout_service,
):
    context = MagicMock(spec=AgentToolContext)
    context.user_id = user_id
    context.workout_service = workout_service
    tools = build_workout_read_tools(context)
    return next(tool for tool in tools if tool.name == "read_recent_workouts")


def make_history(*, has_more: bool = False) -> WorkoutHistoryResponse:
    return WorkoutHistoryResponse(
        list=[
            WorkoutHistoryItem(
                id=uuid4(),
                date=date(2026, 9, 1),
                status="completed",
                duration_seconds=3600,
                completed_sets=12,
                total_volume_kg=Decimal("4000.500"),
                pr_count=1,
            ),
            WorkoutHistoryItem(
                id=uuid4(),
                date=date(2026, 9, 3),
                status="interrupted",
                duration_seconds=None,
                completed_sets=4,
                total_volume_kg=Decimal("800.000"),
                pr_count=0,
            ),
        ],
        total=2,
        page=1,
        page_size=100,
        has_more=has_more,
    )


@pytest.mark.asyncio
async def test_recent_workouts_tool_returns_bounded_summary() -> None:
    user_id = uuid4()
    service = make_workout_service()
    service.list_history.return_value = make_history(has_more=True)
    workout_tool = build_workout_tool(
        user_id=user_id,
        workout_service=service,
    )
    current_time = datetime(2026, 9, 3, 12, 0, tzinfo=CHINA_TIMEZONE)

    with patch(
        "nxtrep_backend.agents.tools.workout.datetime",
    ) as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        result = await workout_tool.ainvoke({"days": 14})

    service.list_history.assert_awaited_once_with(
        user_id=user_id,
        start_date=date(2026, 8, 21),
        end_date=date(2026, 9, 3),
        status=None,
        page=1,
        page_size=100,
    )
    assert result["period"] == {
        "days": 14,
        "start_date": "2026-08-21",
        "end_date": "2026-09-03",
    }
    assert result["summary"] == {
        "workout_count": 2,
        "returned_count": 2,
        "completed_workout_count": 1,
        "completed_sets": 16,
        "total_volume_kg": "4800.500",
        "total_duration_seconds": 3600,
        "personal_record_count": 1,
        "has_more": True,
    }
    assert len(result["workouts"]) == 2
    assert result["workouts"][0]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_days, expected_days, expected_start",
    [
        (-10, 1, date(2026, 9, 3)),
        (200, 90, date(2026, 6, 6)),
    ],
)
async def test_recent_workouts_tool_clamps_date_window(
    requested_days: int,
    expected_days: int,
    expected_start: date,
) -> None:
    service = make_workout_service()
    service.list_history.return_value = WorkoutHistoryResponse(
        list=[],
        total=0,
        page=1,
        page_size=100,
        has_more=False,
    )
    workout_tool = build_workout_tool(
        user_id=uuid4(),
        workout_service=service,
    )
    current_time = datetime(2026, 9, 3, 12, 0, tzinfo=CHINA_TIMEZONE)

    with patch(
        "nxtrep_backend.agents.tools.workout.datetime",
    ) as mocked_datetime:
        mocked_datetime.now.return_value = current_time
        result = await workout_tool.ainvoke({"days": requested_days})

    assert result["period"]["days"] == expected_days
    assert service.list_history.await_args.kwargs["start_date"] == (expected_start)


def test_recent_workouts_tool_only_exposes_days_to_model() -> None:
    workout_tool = build_workout_tool(
        user_id=uuid4(),
        workout_service=make_workout_service(),
    )

    properties = workout_tool.args_schema.model_json_schema()["properties"]
    assert set(properties) == {"days"}
    assert "user_id" not in properties


@pytest.mark.asyncio
async def test_exercise_history_tool_returns_set_performance() -> None:
    user_id = uuid4()
    exercise_id = uuid4()
    service = make_workout_service()
    service.list_exercise_history.return_value = [
        SimpleNamespace(
            workout=SimpleNamespace(
                id=uuid4(),
                started_at=datetime(2026, 9, 1, tzinfo=CHINA_TIMEZONE),
                status="completed",
            ),
            exercise=SimpleNamespace(
                name_snapshot="卧推",
                target_snapshot={"sets": 3, "rep_min": 8},
            ),
            sets=[
                SimpleNamespace(
                    set_index=1,
                    weight_kg=Decimal("80.000"),
                    reps=8,
                    rir=2,
                    rpe=None,
                    tags=["working"],
                )
            ],
        )
    ]
    current_tool = next(
        item
        for item in build_workout_read_tools(
            MagicMock(
                spec=AgentToolContext,
                user_id=user_id,
                workout_service=service,
            )
        )
        if item.name == "read_exercise_history"
    )

    result = await current_tool.ainvoke({"exercise_id": str(exercise_id), "limit": 5})

    assert result["sessions"][0]["sets"][0] == {
        "set_index": 1,
        "weight_kg": "80.000",
        "reps": 8,
        "rir": 2,
        "rpe": None,
        "tags": ["working"],
    }
    service.list_exercise_history.assert_awaited_once_with(
        user_id=user_id,
        exercise_id=exercise_id,
        limit=5,
    )
