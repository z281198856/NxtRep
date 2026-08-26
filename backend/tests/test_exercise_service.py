from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import Exercise
from nxtrep_backend.repositories.exercise import (
    ExerciseDetailRecord,
    ExercisePage,
    ExerciseUpdateState,
    SqlAlchemyExercisesRepository,
)
from nxtrep_backend.services.exercise import (
    ExerciseCreateData,
    ExerciseMuscleOverlapError,
    ExerciseNotFoundError,
    ExercisesService,
    ExerciseStateError,
    ExerciseUpdateData,
    ExerciseVersionConflictError,
)


@pytest.mark.asyncio
async def test_list_exercises_forwards_filters_and_reports_more_pages() -> None:
    user_id = uuid4()
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.list_exercises = AsyncMock(return_value=ExercisePage(items=[], total=41))
    service = ExercisesService(repository)

    result = await service.list_exercises(
        user_id=user_id,
        keyword="深蹲",
        equipment="barbell",
        muscle="quadriceps",
        page=2,
        page_size=20,
    )

    assert result.items == []
    assert result.total == 41
    assert result.page == 2
    assert result.page_size == 20
    assert result.has_more is True
    repository.list_exercises.assert_awaited_once_with(
        user_id=user_id,
        keyword="深蹲",
        equipment="barbell",
        muscle="quadriceps",
        page=2,
        page_size=20,
    )


@pytest.mark.asyncio
async def test_list_exercises_reports_no_more_pages_at_boundary() -> None:
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.list_exercises = AsyncMock(return_value=ExercisePage(items=[], total=40))
    service = ExercisesService(repository)

    result = await service.list_exercises(
        user_id=uuid4(),
        keyword=None,
        equipment=None,
        muscle=None,
        page=2,
        page_size=20,
    )

    assert result.has_more is False


@pytest.mark.asyncio
async def test_get_exercise_detail_returns_repository_record() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=None,
        name_zh="杠铃深蹲",
        equipment="barbell",
    )
    record = ExerciseDetailRecord(
        exercise=exercise,
        aliases=["深蹲"],
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstring"],
        substitutions=[],
    )
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.get_exercise_detail = AsyncMock(return_value=record)
    service = ExercisesService(repository)

    result = await service.get_exercise_detail(
        user_id=user_id,
        exercise_id=exercise.id,
    )

    assert result is record
    repository.get_exercise_detail.assert_awaited_once_with(
        user_id=user_id,
        exercise_id=exercise.id,
    )


@pytest.mark.asyncio
async def test_get_exercise_detail_raises_not_found_for_invisible_record() -> None:
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.get_exercise_detail = AsyncMock(return_value=None)
    service = ExercisesService(repository)

    with pytest.raises(ExerciseNotFoundError):
        await service.get_exercise_detail(
            user_id=uuid4(),
            exercise_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_custom_exercise_builds_owned_exercise_and_muscles() -> None:
    user_id = uuid4()
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.save_custom_exercise = AsyncMock()
    service = ExercisesService(repository)
    data = ExerciseCreateData(
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        primary_muscles=["quadriceps", "gluteus"],
        secondary_muscles=["hamstring"],
        notes="家里训练使用",
    )

    result = await service.create_custom_exercise(
        user_id=user_id,
        data=data,
    )

    call = repository.save_custom_exercise.await_args
    exercise = call.kwargs["exercise"]
    muscles = call.kwargs["muscles"]

    assert exercise.id is not None
    assert exercise.owner_user_id == user_id
    assert exercise.name_zh == "高脚杯深蹲"
    assert exercise.equipment == "dumbbell"
    assert exercise.notes == "家里训练使用"
    assert exercise.version == 1
    assert exercise.instructions == []
    assert exercise.breathing == []
    assert exercise.common_errors == []
    assert exercise.safety_notes == []
    assert [(muscle.exercise_id, muscle.muscle_code, muscle.role) for muscle in muscles] == [
        (exercise.id, "quadriceps", "primary"),
        (exercise.id, "gluteus", "primary"),
        (exercise.id, "hamstring", "secondary"),
    ]
    assert result.exercise is exercise
    assert result.aliases == []
    assert result.primary_muscles == ["quadriceps", "gluteus"]
    assert result.secondary_muscles == ["hamstring"]
    assert result.substitutions == []


def make_update_repository(
    state: ExerciseUpdateState | None,
    detail: ExerciseDetailRecord | None = None,
) -> SqlAlchemyExercisesRepository:
    repository = MagicMock(spec=SqlAlchemyExercisesRepository)
    repository.get_custom_exercise_for_update = AsyncMock(return_value=state)
    repository.save_custom_exercise_update = AsyncMock()
    repository.get_exercise_detail = AsyncMock(return_value=detail)
    return repository


@pytest.mark.asyncio
async def test_update_custom_exercise_mutates_fields_and_increments_version() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="旧动作名称",
        equipment="dumbbell",
        notes="旧备注",
        version=2,
    )
    state = ExerciseUpdateState(
        exercise=exercise,
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstring"],
    )
    detail = ExerciseDetailRecord(
        exercise=exercise,
        aliases=[],
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstring"],
        substitutions=[],
    )
    repository = make_update_repository(state, detail)
    service = ExercisesService(repository)

    result = await service.update_custom_exercise(
        user_id=user_id,
        exercise_id=exercise.id,
        data=ExerciseUpdateData(
            name_zh="新动作名称",
            equipment="barbell",
            primary_muscles=None,
            secondary_muscles=None,
            notes=None,
            supplied_fields=frozenset({"name_zh", "equipment", "notes"}),
        ),
        expected_version=2,
    )

    assert exercise.name_zh == "新动作名称"
    assert exercise.equipment == "barbell"
    assert exercise.notes is None
    assert exercise.version == 3
    repository.save_custom_exercise_update.assert_awaited_once_with(
        exercise=exercise,
        muscles=None,
    )
    assert result is detail


@pytest.mark.asyncio
async def test_update_custom_exercise_rebuilds_complete_muscle_set() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=2,
    )
    state = ExerciseUpdateState(
        exercise=exercise,
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstring"],
    )
    detail = ExerciseDetailRecord(
        exercise=exercise,
        aliases=[],
        primary_muscles=["gluteus"],
        secondary_muscles=["hamstring"],
        substitutions=[],
    )
    repository = make_update_repository(state, detail)
    service = ExercisesService(repository)

    await service.update_custom_exercise(
        user_id=user_id,
        exercise_id=exercise.id,
        data=ExerciseUpdateData(
            name_zh=None,
            equipment=None,
            primary_muscles=["gluteus"],
            secondary_muscles=None,
            notes=None,
            supplied_fields=frozenset({"primary_muscles"}),
        ),
        expected_version=2,
    )

    call = repository.save_custom_exercise_update.await_args
    muscles = call.kwargs["muscles"]
    assert [(muscle.muscle_code, muscle.role) for muscle in muscles] == [
        ("gluteus", "primary"),
        ("hamstring", "secondary"),
    ]
    assert exercise.version == 3


@pytest.mark.asyncio
async def test_update_custom_exercise_rejects_stale_version() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=3,
    )
    state = ExerciseUpdateState(
        exercise=exercise,
        primary_muscles=["quadriceps"],
        secondary_muscles=[],
    )
    repository = make_update_repository(state)
    service = ExercisesService(repository)

    with pytest.raises(ExerciseVersionConflictError) as error:
        await service.update_custom_exercise(
            user_id=exercise.owner_user_id,
            exercise_id=exercise.id,
            data=ExerciseUpdateData(
                name_zh="新名称",
                equipment=None,
                primary_muscles=None,
                secondary_muscles=None,
                notes=None,
                supplied_fields=frozenset({"name_zh"}),
            ),
            expected_version=2,
        )

    assert error.value.expected_version == 2
    assert error.value.current_version == 3
    repository.save_custom_exercise_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_custom_exercise_rejects_overlap_with_preserved_muscles() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=2,
    )
    state = ExerciseUpdateState(
        exercise=exercise,
        primary_muscles=["quadriceps"],
        secondary_muscles=["hamstring"],
    )
    repository = make_update_repository(state)
    service = ExercisesService(repository)

    with pytest.raises(ExerciseMuscleOverlapError):
        await service.update_custom_exercise(
            user_id=exercise.owner_user_id,
            exercise_id=exercise.id,
            data=ExerciseUpdateData(
                name_zh=None,
                equipment=None,
                primary_muscles=["hamstring"],
                secondary_muscles=None,
                notes=None,
                supplied_fields=frozenset({"primary_muscles"}),
            ),
            expected_version=2,
        )

    repository.save_custom_exercise_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_custom_exercise_rejects_missing_or_invalid_state() -> None:
    missing_repository = make_update_repository(None)
    missing_service = ExercisesService(missing_repository)

    with pytest.raises(ExerciseNotFoundError):
        await missing_service.update_custom_exercise(
            user_id=uuid4(),
            exercise_id=uuid4(),
            data=ExerciseUpdateData(
                name_zh="新名称",
                equipment=None,
                primary_muscles=None,
                secondary_muscles=None,
                notes=None,
                supplied_fields=frozenset({"name_zh"}),
            ),
            expected_version=1,
        )

    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=1,
    )
    invalid_repository = make_update_repository(
        ExerciseUpdateState(
            exercise=exercise,
            primary_muscles=["quadriceps"],
            secondary_muscles=[],
        ),
        detail=None,
    )
    invalid_service = ExercisesService(invalid_repository)

    with pytest.raises(ExerciseStateError):
        await invalid_service.update_custom_exercise(
            user_id=exercise.owner_user_id,
            exercise_id=exercise.id,
            data=ExerciseUpdateData(
                name_zh="新名称",
                equipment=None,
                primary_muscles=None,
                secondary_muscles=None,
                notes=None,
                supplied_fields=frozenset({"name_zh"}),
            ),
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_delete_custom_exercise_soft_deletes_and_increments_version() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=2,
    )
    repository = make_update_repository(
        ExerciseUpdateState(
            exercise=exercise,
            primary_muscles=["quadriceps"],
            secondary_muscles=["hamstring"],
        )
    )
    service = ExercisesService(repository)
    before_delete = datetime.now(UTC)

    result = await service.delete_custom_exercise(
        user_id=user_id,
        exercise_id=exercise.id,
        expected_version=2,
    )

    after_delete = datetime.now(UTC)
    assert result is None
    assert exercise.deleted_at is not None
    assert before_delete <= exercise.deleted_at <= after_delete
    assert exercise.deleted_at.tzinfo is UTC
    assert exercise.version == 3
    repository.save_custom_exercise_update.assert_awaited_once_with(
        exercise=exercise,
        muscles=None,
    )


@pytest.mark.asyncio
async def test_delete_custom_exercise_rejects_stale_version() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=3,
    )
    repository = make_update_repository(
        ExerciseUpdateState(
            exercise=exercise,
            primary_muscles=["quadriceps"],
            secondary_muscles=[],
        )
    )
    service = ExercisesService(repository)

    with pytest.raises(ExerciseVersionConflictError) as error:
        await service.delete_custom_exercise(
            user_id=exercise.owner_user_id,
            exercise_id=exercise.id,
            expected_version=2,
        )

    assert error.value.expected_version == 2
    assert error.value.current_version == 3
    assert exercise.deleted_at is None
    repository.save_custom_exercise_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_custom_exercise_rejects_missing_or_unowned_exercise() -> None:
    repository = make_update_repository(None)
    service = ExercisesService(repository)

    with pytest.raises(ExerciseNotFoundError):
        await service.delete_custom_exercise(
            user_id=uuid4(),
            exercise_id=uuid4(),
            expected_version=1,
        )

    repository.save_custom_exercise_update.assert_not_awaited()
