from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.api.routes.workout import _workout_response
from nxtrep_backend.db.models import Workout, WorkoutExercise, WorkoutSet
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository, WorkoutAggregate
from nxtrep_backend.schemas.workout import (
    WorkoutExerciseTargetUpdateRequest,
    WorkoutPauseRequest,
    WorkoutResumeRequest,
)
from nxtrep_backend.services.workout import (
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutService,
    WorkoutTargetError,
)


def setup_workout():
    now = datetime.now(UTC)
    workout = Workout(
        id=uuid4(),
        user_id=uuid4(),
        status="in_progress",
        version=3,
        started_at=now - timedelta(minutes=10),
        total_paused_seconds=0,
        pre_check={},
        pain=[],
    )
    exercise = WorkoutExercise(
        id=uuid4(),
        workout_id=workout.id,
        name_snapshot="卧推",
        order_no=1,
        target_snapshot={"sets": 4, "rep_min": 8, "rep_max": 12, "rest_seconds": 90},
        replacement_history=[],
    )
    completed = WorkoutSet(
        id=uuid4(),
        workout_id=workout.id,
        workout_exercise_id=exercise.id,
        client_generated_id=uuid4(),
        set_index=1,
        weight_kg=55,
        reps=8,
        completed_at=now - timedelta(seconds=10),
        tags=[],
        version=1,
    )
    aggregate = WorkoutAggregate(workout, [exercise], {exercise.id: [completed]})
    repository = MagicMock(spec=SqlAlchemyWorkoutRepository)
    repository.session = MagicMock()
    repository.session.flush = AsyncMock()
    repository.get_workout = AsyncMock(return_value=workout)
    repository.get_workout_exercise = AsyncMock(return_value=exercise)
    repository.get_aggregate = AsyncMock(return_value=aggregate)
    service = WorkoutService(repository, MagicMock(spec=SqlAlchemyTrainingRepository))
    return service, repository, aggregate


@pytest.mark.asyncio
async def test_adjust_target_preserves_completed_sets_and_other_exercise_values():
    service, repository, aggregate = setup_workout()
    workout, exercise = aggregate.workout, aggregate.exercises[0]
    result = await service.update_exercise_target(
        workout.user_id,
        workout.id,
        exercise.id,
        WorkoutExerciseTargetUpdateRequest(
            target_sets=6, rest_seconds=120, expected_workout_version=3
        ),
    )
    assert result.exercises[0].target_snapshot == {
        "sets": 6,
        "rep_min": 8,
        "rep_max": 12,
        "rest_seconds": 120,
    }
    assert len(result.sets_by_exercise[exercise.id]) == 1
    assert workout.version == 4
    repository.get_workout.assert_awaited_once_with(workout.user_id, workout.id, lock=True)
    response = _workout_response(result)
    assert response.rest_timer.duration_seconds == 120
    assert 108 <= response.rest_timer.remaining_seconds <= 110


@pytest.mark.asyncio
@pytest.mark.parametrize("status,version", [("paused", 3), ("completed", 3), ("in_progress", 2)])
async def test_target_change_rejects_stale_or_non_active_workout(status, version):
    service, _, aggregate = setup_workout()
    aggregate.workout.status = status
    with pytest.raises(WorkoutConflictError):
        await service.update_exercise_target(
            aggregate.workout.user_id,
            aggregate.workout.id,
            aggregate.exercises[0].id,
            WorkoutExerciseTargetUpdateRequest(target_sets=5, expected_workout_version=version),
        )
    assert aggregate.exercises[0].target_snapshot["sets"] == 4


@pytest.mark.asyncio
async def test_target_cannot_remove_completed_sets_or_reach_other_workout():
    service, repository, aggregate = setup_workout()
    exercise = aggregate.exercises[0]
    aggregate.sets_by_exercise[exercise.id] *= 3
    with pytest.raises(WorkoutTargetError, match="已经完成 3 组"):
        await service.update_exercise_target(
            aggregate.workout.user_id,
            aggregate.workout.id,
            exercise.id,
            WorkoutExerciseTargetUpdateRequest(target_sets=2, expected_workout_version=3),
        )
    repository.get_workout_exercise.return_value = None
    with pytest.raises(WorkoutNotFoundError):
        await service.update_exercise_target(
            aggregate.workout.user_id,
            aggregate.workout.id,
            uuid4(),
            WorkoutExerciseTargetUpdateRequest(target_sets=5, expected_workout_version=3),
        )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"target_sets": None},
        {"target_sets": 0},
        {"target_sets": 21},
        {"rest_seconds": -1},
        {"rest_seconds": 1801},
        {"rest_seconds": None},
    ],
)
def test_target_schema_rejects_invalid_settings(fields):
    with pytest.raises(ValidationError):
        WorkoutExerciseTargetUpdateRequest(expected_workout_version=1, **fields)


@pytest.mark.asyncio
async def test_rest_freezes_during_pause_and_survives_two_resumes():
    service, _, aggregate = setup_workout()
    workout = aggregate.workout
    exercise = aggregate.exercises[0]
    completed = aggregate.sets_by_exercise[exercise.id][0]
    paused_at = completed.completed_at + timedelta(seconds=20)
    await service.pause_workout(
        workout.user_id, workout.id, WorkoutPauseRequest(paused_at=paused_at, expected_version=3)
    )
    paused = _workout_response(aggregate)
    assert paused.rest_timer.remaining_seconds == 70
    await service.resume_workout(
        workout.user_id,
        workout.id,
        WorkoutResumeRequest(resumed_at=paused_at + timedelta(seconds=60), expected_version=4),
    )
    assert exercise.target_snapshot["rest_timer_pause"]["seconds"] == 60
    paused_at += timedelta(seconds=70)
    await service.pause_workout(
        workout.user_id, workout.id, WorkoutPauseRequest(paused_at=paused_at, expected_version=5)
    )
    assert _workout_response(aggregate).rest_timer.remaining_seconds == 60
    await service.resume_workout(
        workout.user_id,
        workout.id,
        WorkoutResumeRequest(resumed_at=paused_at + timedelta(seconds=30), expected_version=6),
    )
    assert exercise.target_snapshot["rest_timer_pause"]["seconds"] == 90


@pytest.mark.asyncio
async def test_zero_rest_turns_off_countdown():
    service, _, aggregate = setup_workout()
    await service.update_exercise_target(
        aggregate.workout.user_id,
        aggregate.workout.id,
        aggregate.exercises[0].id,
        WorkoutExerciseTargetUpdateRequest(rest_seconds=0, expected_workout_version=3),
    )
    assert _workout_response(aggregate).rest_timer is None
