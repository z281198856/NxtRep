from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Exercise, ExerciseMuscle
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository


def compile_statement(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_list_exercises_applies_visibility_filters_and_hydrates_entries() -> None:
    user_id = uuid4()
    exercise = Exercise(
        owner_user_id=None,
        name_zh="杠铃深蹲",
        equipment="barbell",
    )
    exercise.id = uuid4()

    scalar_result = MagicMock()
    scalar_result.all.return_value = [exercise]
    alias_result = MagicMock()
    alias_result.all.return_value = [(exercise.id, "深蹲")]
    muscle_result = MagicMock()
    muscle_result.all.return_value = [(exercise.id, "quadriceps")]

    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=1)
    session.scalars = AsyncMock(return_value=scalar_result)
    session.execute = AsyncMock(side_effect=[alias_result, muscle_result])
    repository = SqlAlchemyExercisesRepository(session)

    result = await repository.list_exercises(
        user_id=user_id,
        keyword="深蹲",
        equipment="barbell",
        muscle="quadriceps",
        page=2,
        page_size=10,
    )

    assert result.total == 1
    assert result.items[0].exercise is exercise
    assert result.items[0].aliases == ["深蹲"]
    assert result.items[0].primary_muscles == ["quadriceps"]

    count_sql = compile_statement(session.scalar.await_args.args[0])
    page_sql = compile_statement(session.scalars.await_args.args[0])

    for sql in (count_sql, page_sql):
        assert "exercises.deleted_at IS NULL" in sql
        assert "exercises.owner_user_id IS NULL" in sql
        assert str(user_id) in sql
        assert "exercise_aliases.normalized_alias" in sql
        assert "exercise_muscles.muscle_code = 'quadriceps'" in sql
        assert "exercises.equipment = 'barbell'" in sql

    assert "LIMIT 10 OFFSET 10" in page_sql
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_exercises_does_not_load_children_for_empty_page() -> None:
    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=0)
    session.scalars = AsyncMock(return_value=scalar_result)
    session.execute = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    result = await repository.list_exercises(
        user_id=uuid4(),
        keyword=None,
        equipment=None,
        muscle=None,
        page=1,
        page_size=20,
    )

    assert result.items == []
    assert result.total == 0
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_exercises_escapes_like_wildcards() -> None:
    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=0)
    session.scalars = AsyncMock(return_value=scalar_result)
    session.execute = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    await repository.list_exercises(
        user_id=uuid4(),
        keyword=r"100%_safe\name",
        equipment=None,
        muscle=None,
        page=1,
        page_size=20,
    )

    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())

    assert r"%100\%\_safe\\name%" in compiled.params.values()


@pytest.mark.asyncio
async def test_get_exercise_detail_hydrates_related_data_and_visibility_sql() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=None,
        name_zh="杠铃深蹲",
        equipment="barbell",
    )
    target = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
    )
    alias_result = MagicMock()
    alias_result.all.return_value = ["深蹲"]
    muscle_result = MagicMock()
    muscle_result.all.return_value = [
        ("primary", "quadriceps"),
        ("secondary", "hamstring"),
    ]
    substitution_result = MagicMock()
    substitution_result.all.return_value = [(target, "无杠铃时可替代")]

    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=exercise)
    session.scalars = AsyncMock(return_value=alias_result)
    session.execute = AsyncMock(side_effect=[muscle_result, substitution_result])
    repository = SqlAlchemyExercisesRepository(session)

    result = await repository.get_exercise_detail(
        user_id=user_id,
        exercise_id=exercise.id,
    )

    assert result is not None
    assert result.exercise is exercise
    assert result.aliases == ["深蹲"]
    assert result.primary_muscles == ["quadriceps"]
    assert result.secondary_muscles == ["hamstring"]
    assert result.substitutions[0].exercise is target
    assert result.substitutions[0].reason == "无杠铃时可替代"

    detail_sql = compile_statement(session.scalar.await_args.args[0])
    substitution_sql = compile_statement(session.execute.await_args_list[1].args[0])
    assert "exercises.deleted_at IS NULL" in detail_sql
    assert "exercises.owner_user_id IS NULL" in detail_sql
    assert str(user_id) in detail_sql
    assert "exercise_substitutions.priority" in substitution_sql
    assert "exercises.deleted_at IS NULL" in substitution_sql
    assert str(user_id) in substitution_sql


@pytest.mark.asyncio
async def test_get_exercise_detail_stops_when_exercise_is_not_visible() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock()
    session.execute = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    result = await repository.get_exercise_detail(
        user_id=uuid4(),
        exercise_id=uuid4(),
    )

    assert result is None
    session.scalars.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_custom_exercise_adds_entities_and_flushes_without_commit() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
    )
    muscles = [
        ExerciseMuscle(
            exercise_id=exercise.id,
            muscle_code="quadriceps",
            role="primary",
        ),
        ExerciseMuscle(
            exercise_id=exercise.id,
            muscle_code="hamstring",
            role="secondary",
        ),
    ]
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    await repository.save_custom_exercise(
        exercise=exercise,
        muscles=muscles,
    )

    session.add.assert_called_once_with(exercise)
    session.add_all.assert_called_once_with(muscles)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_custom_exercise_for_update_locks_owned_exercise() -> None:
    user_id = uuid4()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=2,
    )
    muscle_result = MagicMock()
    muscle_result.all.return_value = [
        ("primary", "quadriceps"),
        ("secondary", "hamstring"),
    ]
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=exercise)
    session.execute = AsyncMock(return_value=muscle_result)
    repository = SqlAlchemyExercisesRepository(session)

    state = await repository.get_custom_exercise_for_update(
        user_id=user_id,
        exercise_id=exercise.id,
    )

    assert state is not None
    assert state.exercise is exercise
    assert state.primary_muscles == ["quadriceps"]
    assert state.secondary_muscles == ["hamstring"]
    statement_sql = compile_statement(session.scalar.await_args.args[0])
    assert "FOR UPDATE" in statement_sql
    assert "exercises.owner_user_id" in statement_sql
    assert str(user_id) in statement_sql
    assert "exercises.deleted_at IS NULL" in statement_sql


@pytest.mark.asyncio
async def test_get_custom_exercise_for_update_stops_when_not_owned() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    state = await repository.get_custom_exercise_for_update(
        user_id=uuid4(),
        exercise_id=uuid4(),
    )

    assert state is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_custom_exercise_update_replaces_muscles_atomically() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        version=3,
    )
    muscles = [
        ExerciseMuscle(
            exercise_id=exercise.id,
            muscle_code="quadriceps",
            role="primary",
        )
    ]
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    await repository.save_custom_exercise_update(
        exercise=exercise,
        muscles=muscles,
    )

    delete_sql = compile_statement(session.execute.await_args.args[0])
    assert "DELETE FROM exercise_muscles" in delete_sql
    assert str(exercise.id) in delete_sql
    session.add_all.assert_called_once_with(muscles)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_custom_exercise_update_preserves_unsupplied_muscles() -> None:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=uuid4(),
        name_zh="新动作名称",
        equipment="dumbbell",
        version=3,
    )
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    repository = SqlAlchemyExercisesRepository(session)

    await repository.save_custom_exercise_update(
        exercise=exercise,
        muscles=None,
    )

    session.execute.assert_not_awaited()
    session.add_all.assert_not_called()
    session.flush.assert_awaited_once_with()
