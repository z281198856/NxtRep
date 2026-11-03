import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from nxtrep_backend.db.models import (
    Exercise,
    User,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutSetRevision,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.workout_record import (
    WorkoutRecordDraftRequest,
    WorkoutRecordUpdateRequest,
    WorkoutRecordVoidRequest,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.workout import WorkoutNotFoundError, WorkoutService
from nxtrep_backend.services.workout_record import WorkoutRecordService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"record-agent-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    exercises = [
        Exercise(owner_user_id=user.id, name_zh=name, equipment="barbell")
        for name in ("验收平板卧推", "验收上斜卧推")
    ]
    session.add_all(exercises)
    await session.flush()
    repository = SqlAlchemyConfirmationRepository(session)
    workout = WorkoutService(
        SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
    )
    service = WorkoutRecordService(
        workout, repository, ExercisesService(SqlAlchemyExercisesRepository(session))
    )
    return user, exercises, service, DatabaseConfirmationService(repository)


async def create_and_approve(user, exercise, service, commands):
    card = await service.propose_record(
        user.id, WorkoutRecordDraftRequest(exercise_id=exercise.id, weight_kg=60, sets=4, reps=8)
    )
    await commands.approve(user.id, card.id, card.version)
    return card


@pytest.mark.asyncio
async def test_correct_set_count_reduces_then_adds_without_duplicate_indices_or_new_workout():
    from datetime import UTC, datetime
    from uuid import UUID

    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            original = await create_and_approve(user, exercises[0], service, commands)
            wid, eid = (
                UUID(original.result["workout_id"]), UUID(original.result["workout_exercise_id"])
            )
            for count in (3, 5):
                selected = (await service.read_for_change(user.id, workout_id=wid,
                    workout_exercise_id=eid))["selected_record"]
                before = await service.workout_service.get_aggregate(user.id, wid)
                if count == 5:
                    before.workout.status = "completed"
                    before.workout.ended_at = datetime.now(UTC)
                    await session.flush()
                draft = await service.propose_change(user.id, wid, eid, WorkoutRecordUpdateRequest(
                    expected_workout_version=selected["expected_workout_version"],
                    set_versions=selected["set_versions"], sets=count,
                    weight_kg=55, reason="纠正组数"))
                assert len(draft.after["preview"]["after_sets"]) == count
                assert len(before.sets_by_exercise[eid]) == (4 if count == 3 else 3)
                await commands.approve(user.id, draft.id, draft.version)
                actual = await service.workout_service.get_aggregate(user.id, wid)
                assert len(actual.sets_by_exercise[eid]) == count
                assert all(item.weight_kg == 55 and item.reps == 8
                           for item in actual.sets_by_exercise[eid])
                assert len(draft.result["set_versions"]) == count
            all_rows = list(await session.scalars(
                select(WorkoutSet).where(WorkoutSet.workout_id == wid)
            ))
            assert len(all_rows) == 6 and len({s.set_index for s in all_rows}) == 6
            assert sum(s.voided_at is not None for s in all_rows) == 1
            assert await session.scalar(select(func.count()).select_from(Workout).where(
                Workout.user_id == user.id
            )) == 1
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_record_correct_append_and_void_reuse_one_session_and_preserve_other_exercise():
    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            card = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_name=exercises[0].name_zh, weight_kg=60, sets=4, reps=8
                ),
            )
            assert card.operation_type == "workout_record_create"
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user.id)
                )
                == 0
            )
            await commands.approve(user.id, card.id, card.version)
            result = card.result
            assert result["success"] and result["status"] == "in_progress"
            assert len(result["sets"]) == 4
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, 1)
            from uuid import UUID

            workout_id, item_id = UUID(result["workout_id"]), UUID(result["workout_exercise_id"])
            selected = (
                await service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=item_id
                )
            )["selected_record"]
            correction = await service.propose_change(
                user.id,
                workout_id,
                item_id,
                WorkoutRecordUpdateRequest(
                    expected_workout_version=selected["expected_workout_version"],
                    set_versions=selected["set_versions"],
                    weight_kg=55,
                    reason="重量误记",
                ),
            )
            aggregate = await service.workout_service.get_aggregate(user.id, workout_id)
            assert all(item.weight_kg == 60 for item in aggregate.sets_by_exercise[item_id])
            await commands.approve(user.id, correction.id, correction.version)
            assert all(Decimal(item["weight_kg"]) == 55 for item in correction.result["sets"])
            append = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_id=exercises[1].id,
                    workout_id=workout_id,
                    expected_workout_version=correction.result["expected_workout_version"],
                    weight_kg=25,
                    sets=2,
                    reps=10,
                ),
            )
            await commands.approve(user.id, append.id, append.version)
            assert append.result["workout_id"] == str(workout_id)
            assert len(append.result["sets"]) == 2
            assert {Decimal(item["weight_kg"]) for item in append.result["sets"]} == {Decimal("25")}
            selected = (
                await service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=item_id
                )
            )["selected_record"]
            deletion = await service.propose_change(
                user.id,
                workout_id,
                item_id,
                WorkoutRecordVoidRequest(
                    expected_workout_version=selected["expected_workout_version"],
                    set_versions=selected["set_versions"],
                    reason="撤销误记动作",
                ),
            )
            await commands.approve(user.id, deletion.id, deletion.version)
            aggregate = await service.workout_service.get_aggregate(user.id, workout_id)
            assert aggregate.workout.status == "in_progress"
            assert aggregate.sets_by_exercise[item_id] == []
            other = next(item for item in aggregate.exercises if item.id != item_id)
            assert len(aggregate.sets_by_exercise[other.id]) == 2
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutSetRevision)
                    .join(WorkoutSet, WorkoutSet.id == WorkoutSetRevision.set_id)
                    .where(WorkoutSet.workout_id == workout_id)
                )
                == 8
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_batch_change_checks_all_versions_before_writing_any_set():
    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            card = await create_and_approve(user, exercises[0], service, commands)
            from uuid import UUID

            workout_id, item_id = (
                UUID(card.result["workout_id"]),
                UUID(card.result["workout_exercise_id"]),
            )
            selected = (
                await service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=item_id
                )
            )["selected_record"]
            correction = await service.propose_change(
                user.id,
                workout_id,
                item_id,
                WorkoutRecordUpdateRequest(
                    expected_workout_version=selected["expected_workout_version"],
                    set_versions=selected["set_versions"],
                    weight_kg=55,
                    reason="更正",
                ),
            )
            last_id = UUID(selected["set_versions"][-1]["set_id"])
            await session.execute(
                update(WorkoutSet).where(WorkoutSet.id == last_id).values(version=2)
            )
            with pytest.raises(DatabaseConfirmationConflictError, match="训练组已被修改"):
                await commands.approve(user.id, correction.id, correction.version)
            actual = list(
                await session.scalars(select(WorkoutSet).where(WorkoutSet.workout_id == workout_id))
            )
            assert len(actual) == 4 and all(item.weight_kg == 60 for item in actual)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutSetRevision)
                    .join(WorkoutSet, WorkoutSet.id == WorkoutSetRevision.set_id)
                    .where(WorkoutSet.workout_id == workout_id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_create_failure_rolls_back_entire_business_action_and_cancel_never_records(
    monkeypatch,
):
    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            card = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_id=exercises[0].id, weight_kg=60, sets=4, reps=8
                ),
            )
            user_id = user.id
            original = WorkoutService.create_set
            calls = 0

            async def fail_second(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("模拟工具中途失败")
                return await original(self, *args, **kwargs)

            monkeypatch.setattr(WorkoutService, "create_set", fail_second)
            with pytest.raises(DatabaseConfirmationConflictError, match="模拟工具中途失败"):
                await commands.approve(user_id, card.id, card.version)
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutExercise)
                    .join(Workout, Workout.id == WorkoutExercise.workout_id)
                    .where(Workout.user_id == user_id)
                )
                == 0
            )
            await commands.cancel(user_id, card.id, card.version)
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user_id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_workout_record_permissions_and_ambiguous_exercise_are_not_guessed():
    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            foreign, foreign_exercises, _, _ = await seed(session)
            with pytest.raises(WorkoutNotFoundError):
                await service.propose_record(
                    user.id,
                    WorkoutRecordDraftRequest(
                        exercise_id=foreign_exercises[0].id, weight_kg=60, sets=4, reps=8
                    ),
                )
            ambiguous = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(exercise_name="验收", weight_kg=60, sets=4, reps=8),
            )
            assert ambiguous["status"] == "needs_review" and len(ambiguous["candidates"]) == 2
            card = await create_and_approve(user, exercises[0], service, commands)
            from uuid import UUID

            with pytest.raises(WorkoutNotFoundError):
                await service.read_for_change(
                    foreign.id, workout_id=UUID(card.result["workout_id"])
                )
            pending = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_id=exercises[1].id,
                    workout_id=UUID(card.result["workout_id"]),
                    expected_workout_version=card.result["expected_workout_version"],
                    weight_kg=20,
                    sets=2,
                    reps=10,
                ),
            )
            with pytest.raises(DatabaseConfirmationNotFoundError):
                await commands.approve(foreign.id, pending.id, pending.version)
        finally:
            await session.rollback()
