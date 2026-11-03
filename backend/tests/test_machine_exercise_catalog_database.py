import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_workout_record_database import seed

from nxtrep_backend.db.models import Exercise, ExerciseAlias, WorkoutExercise, WorkoutSet
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
from nxtrep_backend.schemas.workout_record import WorkoutRecordDraftRequest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def load_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations/versions/f8c5d3b0a721_expand_machine_exercise_content.py"
    )
    spec = spec_from_file_location("machine_exercise_catalog", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def apply_catalog(session, migration, monkeypatch):
    def apply(sync_session):
        monkeypatch.setattr(migration, "op", SimpleNamespace(execute=sync_session.execute))
        migration.upgrade()

    await session.run_sync(apply)


@pytest.mark.asyncio
async def test_catalog_can_replay_without_duplicate_aliases_or_touching_user_records(monkeypatch):
    migration = load_migration()
    async with SessionFactory() as session:
        try:
            user, _, service, commands = await seed(session)
            custom = Exercise(
                owner_user_id=user.id,
                name_zh="史密斯平板卧推",
                equipment="other",
                instructions=["保留用户自己的说明"],
            )
            session.add(custom)
            await session.flush()
            set_count = await session.scalar(select(func.count()).select_from(WorkoutSet))
            await apply_catalog(session, migration, monkeypatch)
            first_alias_count = await session.scalar(
                select(func.count()).select_from(ExerciseAlias)
            )
            await apply_catalog(session, migration, monkeypatch)
            assert (
                await session.scalar(select(func.count()).select_from(ExerciseAlias))
                == first_alias_count
            )
            assert await session.scalar(select(func.count()).select_from(WorkoutSet)) == set_count
            await session.refresh(custom)
            assert custom.equipment == "other"
            assert custom.instructions == ["保留用户自己的说明"]

            repository = SqlAlchemyExercisesRepository(session)
            for row in migration.EXERCISES:
                detail = await repository.get_exercise_detail(
                    user_id=user.id, exercise_id=row["id"]
                )
                assert detail.exercise.name_zh == row["name_zh"]
                assert len(detail.exercise.instructions) >= 3
                assert detail.exercise.breathing and detail.exercise.common_errors
                assert detail.exercise.safety_notes and detail.exercise.movement_pattern
                assert detail.primary_muscles
                assert set(detail.primary_muscles).isdisjoint(detail.secondary_muscles)

            for alias, canonical in (
                ("史密斯推肩", "史密斯坐姿推肩"),
                ("史密斯平板推胸", "史密斯平板卧推"),
                ("倒蹬机", "腿举机"),
                ("腿屈伸", "坐姿腿屈伸"),
            ):
                matches = await repository.list_exercises(
                    user_id=user.id,
                    keyword=alias,
                    equipment=None,
                    muscle=None,
                    page=1,
                    page_size=100,
                )
                assert matches.total == 1, (alias, matches.total)
                assert matches.items[0].exercise.name_zh == canonical

            card = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_name="史密斯推肩",
                    weight_kg=30,
                    sets=4,
                    reps=12,
                ),
            )
            assert not isinstance(card, dict), card
            assert card.after["preview"]["exercise_name"] == "史密斯坐姿推肩"
            await commands.approve(user.id, card.id, card.version)
            recorded = await session.get(WorkoutExercise, UUID(card.result["workout_exercise_id"]))
            assert recorded.exercise_id == migration.exercise_id("smith-seated-shoulder-press")
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutSet)
                    .where(
                        WorkoutSet.workout_exercise_id == recorded.id,
                    )
                )
                == 4
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_enriching_existing_smith_content_preserves_pending_confirmation(monkeypatch):
    migration = load_migration()
    async with SessionFactory() as session:
        try:
            user, _, service, commands = await seed(session)
            card = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_name="史密斯上斜推胸",
                    weight_kg=30,
                    sets=4,
                    reps=12,
                ),
            )
            assert not isinstance(card, dict), card
            original_version = card.after["exercise_version"]
            await apply_catalog(session, migration, monkeypatch)
            exercise = await session.get(Exercise, migration.SMITH_INCLINE_ID)
            await session.refresh(exercise)
            assert exercise.version == original_version
            assert exercise.instructions and exercise.movement_pattern == "horizontal_push"
            await commands.approve(user.id, card.id, card.version)
            assert card.status == "succeeded"
            recorded = await session.get(WorkoutExercise, UUID(card.result["workout_exercise_id"]))
            assert recorded.exercise_id == migration.SMITH_INCLINE_ID
        finally:
            await session.rollback()
