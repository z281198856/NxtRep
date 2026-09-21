from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import Workout, WorkoutSet
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.services.workout import WorkoutService


def make_service() -> tuple[WorkoutService, MagicMock]:
    repository = MagicMock(spec=SqlAlchemyWorkoutRepository)
    repository.list_workouts = AsyncMock()
    repository.list_sets = AsyncMock()
    repository.count_records = AsyncMock()
    training = MagicMock(spec=SqlAlchemyTrainingRepository)
    return WorkoutService(repository, training), repository


def make_set(*, weight_kg: str, reps: int) -> WorkoutSet:
    return WorkoutSet(
        id=uuid4(),
        workout_id=uuid4(),
        workout_exercise_id=uuid4(),
        client_generated_id=uuid4(),
        set_index=1,
        weight_kg=Decimal(weight_kg),
        reps=reps,
        tags=[],
        completed_at=datetime(2026, 9, 2, tzinfo=UTC),
        version=1,
    )


@pytest.mark.asyncio
async def test_list_history_calculates_duration_volume_and_local_date() -> None:
    service, repository = make_service()
    user_id = uuid4()
    workout_id = uuid4()
    started_at = datetime(2026, 9, 2, 16, 30, tzinfo=UTC)
    workout = Workout(
        id=workout_id,
        user_id=user_id,
        status="completed",
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=75),
        pre_check={},
        pain=[],
        version=1,
    )
    repository.list_workouts.return_value = ([workout], 3)
    repository.list_sets.return_value = [
        make_set(weight_kg="50", reps=10),
        make_set(weight_kg="60", reps=5),
    ]
    repository.count_records.return_value = 2

    result = await service.list_history(
        user_id=user_id,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 3),
        status="completed",
        page=1,
        page_size=2,
    )

    repository.list_workouts.assert_awaited_once_with(
        user_id,
        date(2026, 8, 20),
        date(2026, 9, 3),
        "completed",
        1,
        2,
    )
    repository.list_sets.assert_awaited_once_with(workout_id)
    repository.count_records.assert_awaited_once_with(workout_id)
    assert result.total == 3
    assert result.has_more is True
    assert len(result.list) == 1
    assert result.list[0].date == date(2026, 9, 3)
    assert result.list[0].duration_seconds == 4500
    assert result.list[0].completed_sets == 2
    assert result.list[0].total_volume_kg == Decimal("800")
    assert result.list[0].pr_count == 2


@pytest.mark.asyncio
async def test_list_history_returns_empty_page() -> None:
    service, repository = make_service()
    repository.list_workouts.return_value = ([], 0)

    result = await service.list_history(user_id=uuid4())

    assert result.list == []
    assert result.total == 0
    assert result.has_more is False
    repository.list_sets.assert_not_awaited()
    repository.count_records.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, message",
    [
        (
            {
                "start_date": date(2026, 9, 3),
                "end_date": date(2026, 9, 2),
            },
            "start_date",
        ),
        ({"page": 0}, "page must"),
        ({"page_size": 0}, "page_size"),
        ({"page_size": 101}, "page_size"),
    ],
)
async def test_list_history_rejects_invalid_query_before_database(
    arguments: dict,
    message: str,
) -> None:
    service, repository = make_service()

    with pytest.raises(ValueError, match=message):
        await service.list_history(
            user_id=uuid4(),
            **arguments,
        )

    repository.list_workouts.assert_not_awaited()
