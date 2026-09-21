from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.api.routes.workout import _workout_response
from nxtrep_backend.db.models import Workout, WorkoutExercise, WorkoutSet
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository, WorkoutAggregate
from nxtrep_backend.schemas.workout import (
    WorkoutFinishRequest,
    WorkoutPauseRequest,
    WorkoutResumeRequest,
)
from nxtrep_backend.services.workout import WorkoutService, workout_duration_seconds


def make_service(workout: Workout) -> tuple[WorkoutService, MagicMock]:
    repository = MagicMock(spec=SqlAlchemyWorkoutRepository)
    repository.session = MagicMock()
    repository.session.flush = AsyncMock()
    repository.get_workout = AsyncMock(return_value=workout)
    repository.get_aggregate = AsyncMock(
        return_value=WorkoutAggregate(workout=workout, exercises=[], sets_by_exercise={})
    )
    repository.list_sets = AsyncMock(return_value=[])
    repository.list_records = AsyncMock(return_value=[])
    repository.add_records = AsyncMock()
    training = MagicMock(spec=SqlAlchemyTrainingRepository)
    return WorkoutService(repository, training), repository


@pytest.mark.asyncio
async def test_pause_resume_and_finish_exclude_paused_time() -> None:
    user_id = uuid4()
    started_at = datetime(2026, 9, 12, 8, tzinfo=UTC)
    workout = Workout(
        id=uuid4(),
        user_id=user_id,
        status="in_progress",
        started_at=started_at,
        total_paused_seconds=0,
        pre_check={},
        pain=[],
        version=1,
    )
    service, repository = make_service(workout)

    paused = await service.pause_workout(
        user_id,
        workout.id,
        WorkoutPauseRequest(paused_at=started_at + timedelta(minutes=10), expected_version=1),
    )

    assert paused.workout.status == "paused"
    assert paused.workout.paused_at == started_at + timedelta(minutes=10)
    assert workout_duration_seconds(workout, started_at + timedelta(minutes=15)) == 600

    resumed = await service.resume_workout(
        user_id,
        workout.id,
        WorkoutResumeRequest(resumed_at=started_at + timedelta(minutes=20), expected_version=2),
    )

    assert resumed.workout.status == "in_progress"
    assert resumed.workout.paused_at is None
    assert resumed.workout.total_paused_seconds == 600
    assert workout_duration_seconds(workout, started_at + timedelta(minutes=30)) == 1200

    result = await service.finish_workout(
        user_id,
        workout.id,
        WorkoutFinishRequest(
            ended_at=started_at + timedelta(minutes=60),
            expected_version=3,
        ),
    )

    assert result["duration_seconds"] == 3000
    assert workout.status == "completed"
    assert workout.version == 4
    repository.add_records.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_finishing_while_paused_closes_current_pause() -> None:
    user_id = uuid4()
    started_at = datetime(2026, 9, 12, 8, tzinfo=UTC)
    workout = Workout(
        id=uuid4(),
        user_id=user_id,
        status="paused",
        started_at=started_at,
        paused_at=started_at + timedelta(minutes=10),
        total_paused_seconds=0,
        pre_check={},
        pain=[],
        version=2,
    )
    service, _ = make_service(workout)

    result = await service.finish_workout(
        user_id,
        workout.id,
        WorkoutFinishRequest(
            ended_at=started_at + timedelta(minutes=30),
            expected_version=2,
        ),
    )

    assert result["duration_seconds"] == 600
    assert workout.total_paused_seconds == 1200
    assert workout.paused_at is None


def test_workout_response_restores_active_rest_timer() -> None:
    now = datetime.now(UTC)
    workout = Workout(
        id=uuid4(),
        user_id=uuid4(),
        status="in_progress",
        started_at=now - timedelta(minutes=5),
        total_paused_seconds=0,
        pre_check={},
        pain=[],
        version=1,
    )
    exercise = WorkoutExercise(
        id=uuid4(),
        workout_id=workout.id,
        exercise_id=uuid4(),
        name_snapshot="深蹲",
        target_snapshot={"sets": 3, "rest_seconds": 120},
        replacement_history=[],
        order_no=1,
    )
    completed_set = WorkoutSet(
        id=uuid4(),
        workout_id=workout.id,
        workout_exercise_id=exercise.id,
        client_generated_id=uuid4(),
        set_index=1,
        weight_kg=100,
        reps=5,
        tags=["working"],
        completed_at=now,
        version=1,
    )

    response = _workout_response(
        WorkoutAggregate(
            workout=workout,
            exercises=[exercise],
            sets_by_exercise={exercise.id: [completed_set]},
        )
    )

    assert response.rest_timer is not None
    assert response.rest_timer.set_id == completed_set.id
    assert response.rest_timer.duration_seconds == 120
    assert 118 <= response.rest_timer.remaining_seconds <= 120
    assert 299 <= response.elapsed_seconds <= 301
