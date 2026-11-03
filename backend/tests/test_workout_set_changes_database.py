import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from nxtrep_backend.db.models import (
    AgentMemory,
    Exercise,
    PersonalRecord,
    User,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutSetRevision,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.workout import (
    ProgressionDraftCreateRequest,
    WorkoutFinishRequest,
    WorkoutSetCorrectionRequest,
    WorkoutSetUpdateRequest,
    WorkoutSetVoidRequest,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.workout import (
    WorkoutNotFoundError,
    WorkoutService,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"workout-edit-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    exercise_id = await session.scalar(
        select(Exercise.id).where(Exercise.deleted_at.is_(None)).limit(1)
    )
    assert exercise_id is not None
    started = datetime.now(UTC) - timedelta(days=1)
    workout = Workout(user_id=user.id, started_at=started, status="in_progress")
    session.add(workout)
    await session.flush()
    exercise = WorkoutExercise(
        workout_id=workout.id,
        exercise_id=exercise_id,
        name_snapshot="验收卧推",
        order_no=1,
        target_snapshot={"sets": 2, "rep_min": 8, "rep_max": 12},
    )
    session.add(exercise)
    await session.flush()
    sets = [
        WorkoutSet(
            workout_id=workout.id,
            workout_exercise_id=exercise.id,
            client_generated_id=uuid4(),
            set_index=index,
            weight_kg=weight,
            reps=reps,
            rir=3,
            tags=["working"],
            completed_at=started + timedelta(minutes=index),
        )
        for index, weight, reps in [(1, 50, 10), (2, 45, 8)]
    ]
    session.add_all(sets)
    await session.flush()
    confirmations = SqlAlchemyConfirmationRepository(session)
    service = WorkoutService(
        SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session), confirmations
    )
    await service.finish_workout(
        user.id,
        workout.id,
        WorkoutFinishRequest(ended_at=started + timedelta(minutes=30), expected_version=1),
    )
    return user, workout, exercise, sets, service, confirmations


@pytest.mark.asyncio
async def test_corrected_workout_summary_personal_records_use_actual_remaining_sets():
    async with SessionFactory() as session:
        try:
            user, workout, _, sets, service, _ = await seed(session)
            await service.update_set(
                user.id,
                workout.id,
                sets[0].id,
                WorkoutSetUpdateRequest(
                    weight_kg=40, reps=7, expected_version=1, reason="更正误记"
                ),
            )
            summary = await service.get_summary(user.id, workout.id)
            assert summary["total_volume_kg"] == Decimal("640")
            prs = {row["record_type"]: Decimal(row["value"]) for row in summary["prs"]}
            assert prs == {"max_weight": Decimal("45"), "max_reps": Decimal("8")}
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_workout_update_then_void_require_confirmation_preserve_other_set_and_revisions():
    async with SessionFactory() as session:
        try:
            user, workout, exercise, sets, service, repo = await seed(session)
            commands = DatabaseConfirmationService(repo)
            old_progression = await service.create_progression_draft(
                user.id, workout.id, ProgressionDraftCreateRequest()
            )
            old_card = await service.submit_progression(
                user.id, workout.id, old_progression.id, old_progression.version
            )
            original_target = dict(exercise.target_snapshot)
            card = await service.propose_set_change(
                user.id,
                workout.id,
                sets[0].id,
                WorkoutSetCorrectionRequest(
                    weight_kg=40, reps=7, expected_version=1, reason="原记录误记"
                ),
            )
            assert sets[0].weight_kg == 50 and sets[0].reps == 10 and sets[0].version == 1
            assert Decimal(card.after["preview"]["volume_before"]) == 860
            assert Decimal(card.after["preview"]["volume_after"]) == 640
            await commands.approve(user.id, card.id, card.version)
            assert sets[0].weight_kg == 40 and sets[0].reps == 7
            assert sets[0].rir == 3 and sets[0].tags == ["working"]
            assert sets[1].weight_kg == 45 and sets[1].reps == 8 and sets[1].version == 1
            assert exercise.target_snapshot == original_target
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, 1)
            with pytest.raises(DatabaseConfirmationConflictError, match="训练记录已更正"):
                await commands.approve(user.id, old_card.id, old_card.version)
            new_progression = await service.create_progression_draft(
                user.id, workout.id, ProgressionDraftCreateRequest()
            )
            assert Decimal(new_progression.suggestions[0]["current_target"]["weight_kg"]) == 45
            deletion = await service.propose_set_change(
                user.id,
                workout.id,
                sets[1].id,
                WorkoutSetVoidRequest(expected_version=1, reason="第二组误记"),
            )
            assert sets[1].voided_at is None
            await commands.approve(user.id, deletion.id, deletion.version)
            assert sets[1].voided_at is not None and sets[0].voided_at is None
            summary = await service.get_summary(user.id, workout.id)
            assert summary["completed_sets"] == 1 and summary["total_volume_kg"] == 280
            assert {p["record_type"]: Decimal(p["value"]) for p in summary["prs"]} == {
                "max_weight": Decimal("40"),
                "max_reps": Decimal("7"),
            }
            assert (await service.get_aggregate(user.id, workout.id)).sets_by_exercise[
                exercise.id
            ] == [sets[0]]
            history = await service.list_history(
                user_id=user.id, start_date=None, end_date=None, status=None, page=1, page_size=20
            )
            assert history.list[0].total_volume_kg == 280 and history.list[0].completed_sets == 1
            rows = list(
                await session.scalars(
                    select(WorkoutSetRevision).where(
                        WorkoutSetRevision.set_id.in_([s.id for s in sets])
                    )
                )
            )
            assert len(rows) == 2 and rows[0].reason
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMemory)
                    .where(AgentMemory.user_id == user.id)
                )
                == 0
            )
            assert exercise.target_snapshot == original_target
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_correction_rebuilds_later_records_without_affecting_other_exercises_or_users():
    async with SessionFactory() as session:
        try:
            user, workout, exercise, sets, service, _ = await seed(session)
            foreign, _, _, _, _, _ = await seed(session)
            foreign_before = [
                (r.id, r.value, r.set_id)
                for r in await session.scalars(
                    select(PersonalRecord).where(PersonalRecord.user_id == foreign.id)
                )
            ]
            other_id = await session.scalar(
                select(Exercise.id)
                .where(Exercise.id != exercise.exercise_id, Exercise.deleted_at.is_(None))
                .limit(1)
            )
            assert other_id is not None
            started = workout.started_at + timedelta(hours=2)
            later = Workout(user_id=user.id, started_at=started, status="in_progress")
            session.add(later)
            await session.flush()
            later_sets = []
            for index, exercise_id, weight, reps in [
                (1, exercise.exercise_id, 46, 9),
                (2, other_id, 80, 12),
            ]:
                item = WorkoutExercise(
                    workout_id=later.id,
                    exercise_id=exercise_id,
                    name_snapshot=f"验收动作{index}",
                    order_no=index,
                    target_snapshot={"sets": 1},
                )
                session.add(item)
                await session.flush()
                recorded = WorkoutSet(
                    workout_id=later.id,
                    workout_exercise_id=item.id,
                    client_generated_id=uuid4(),
                    set_index=1,
                    weight_kg=weight,
                    reps=reps,
                    rir=3,
                    tags=["working"],
                    completed_at=started + timedelta(minutes=index),
                )
                session.add(recorded)
                later_sets.append(recorded)
            await session.flush()
            await service.finish_workout(
                user.id,
                later.id,
                WorkoutFinishRequest(ended_at=started + timedelta(minutes=30), expected_version=1),
            )
            unrelated = [
                (r.id, r.value, r.set_id)
                for r in await session.scalars(
                    select(PersonalRecord).where(
                        PersonalRecord.user_id == user.id, PersonalRecord.exercise_id == other_id
                    )
                )
            ]
            assert len(unrelated) == 2
            assert not list(
                await session.scalars(
                    select(PersonalRecord).where(
                        PersonalRecord.workout_id == later.id,
                        PersonalRecord.exercise_id == exercise.exercise_id,
                    )
                )
            )
            await service.update_set(
                user.id,
                workout.id,
                sets[0].id,
                WorkoutSetUpdateRequest(
                    weight_kg=40, reps=7, expected_version=1, reason="纠正旧误记"
                ),
            )
            rebuilt = list(
                await session.scalars(
                    select(PersonalRecord).where(
                        PersonalRecord.workout_id == later.id,
                        PersonalRecord.exercise_id == exercise.exercise_id,
                    )
                )
            )
            assert {r.record_type: r.value for r in rebuilt} == {
                "max_weight": Decimal(46),
                "max_reps": Decimal(9),
            }
            assert all(r.set_id == later_sets[0].id for r in rebuilt)
            assert [
                (r.id, r.value, r.set_id)
                for r in await session.scalars(
                    select(PersonalRecord).where(
                        PersonalRecord.user_id == user.id, PersonalRecord.exercise_id == other_id
                    )
                )
            ] == unrelated
            assert [
                (r.id, r.value, r.set_id)
                for r in await session.scalars(
                    select(PersonalRecord).where(PersonalRecord.user_id == foreign.id)
                )
            ] == foreign_before
            assert later_sets[0].weight_kg == 46 and later_sets[0].reps == 9
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["update", "void"])
@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_cancelled_and_rejected_workout_changes_do_not_write(action, decision):
    async with SessionFactory() as session:
        try:
            user, workout, _, sets, service, repo = await seed(session)
            body = (
                WorkoutSetCorrectionRequest(reps=6, expected_version=1, reason="更正")
                if action == "update"
                else WorkoutSetVoidRequest(expected_version=1, reason="误记")
            )
            card = await service.propose_set_change(user.id, workout.id, sets[0].id, body)
            commands = DatabaseConfirmationService(repo)
            if decision == "reject":
                await commands.reject(user.id, card.id, card.version, "保留原记录")
            else:
                await commands.cancel(user.id, card.id, card.version)
            assert sets[0].weight_kg == 50 and sets[0].reps == 10 and sets[0].voided_at is None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutSetRevision)
                    .where(WorkoutSetRevision.set_id == sets[0].id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_stale_set_snapshot_and_foreign_account_cannot_change_records():
    async with SessionFactory() as session:
        try:
            user, workout, _, sets, service, repo = await seed(session)
            body = WorkoutSetCorrectionRequest(reps=6, expected_version=1, reason="更正")
            with pytest.raises(WorkoutNotFoundError):
                await service.propose_set_change(uuid4(), workout.id, sets[0].id, body)
            with pytest.raises(WorkoutNotFoundError):
                await service.propose_set_change(user.id, workout.id, uuid4(), body)
            card = await service.propose_set_change(user.id, workout.id, sets[0].id, body)
            commands = DatabaseConfirmationService(repo)
            with pytest.raises(DatabaseConfirmationNotFoundError):
                await commands.approve(uuid4(), card.id, card.version)
            await session.execute(
                update(WorkoutSet)
                .where(WorkoutSet.id == sets[0].id)
                .values(reps=9, version=2)
                .execution_options(synchronize_session=False)
            )
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, card.version)
            assert sets[0].reps == 9 and sets[0].version == 2 and card.status == "pending"
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_other_group_change_invalidates_old_volume_preview():
    async with SessionFactory() as session:
        try:
            user, workout, _, sets, service, repo = await seed(session)
            card = await service.propose_set_change(
                user.id,
                workout.id,
                sets[0].id,
                WorkoutSetCorrectionRequest(reps=6, expected_version=1, reason="更正"),
            )
            await service.update_set(
                user.id,
                workout.id,
                sets[1].id,
                WorkoutSetUpdateRequest(reps=9, expected_version=1, reason="另组更正"),
            )
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert sets[0].reps == 10
        finally:
            await session.rollback()
