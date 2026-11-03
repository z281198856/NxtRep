import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_workout_record_database import seed

from nxtrep_backend.db.models import Workout, WorkoutSet
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.schemas.workout_record import WorkoutRecordDraftRequest

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_smith_incline_records_own_exercise_without_substituting_barbell():
    async with SessionFactory() as session:
        try:
            user, exercises, service, commands = await seed(session)
            rejected = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_id=exercises[0].id,
                    exercise_name="史密斯上斜推胸",
                    weight_kg=30,
                    sets=4,
                    reps=12,
                ),
            )
            assert rejected["error_code"] == "EXERCISE_VARIANT_MISMATCH"
            conversation_id = uuid4()
            card = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_name="史密斯上斜推胸",
                    weight_kg=30,
                    sets=4,
                    reps=12,
                ),
                conversation_id=conversation_id,
            )
            assert not isinstance(card, dict), card
            assert card.after["preview"]["exercise_name"] == "史密斯上斜推胸"
            assert card.after["request"]["exercise_id"] != str(exercises[0].id)
            repeated = await service.propose_record(
                user.id,
                WorkoutRecordDraftRequest(
                    exercise_name="史密斯上斜推胸",
                    weight_kg="30.0",
                    sets=4,
                    reps=12,
                ),
                conversation_id=conversation_id,
            )
            assert repeated.id == card.id
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Workout)
                    .where(
                        Workout.user_id == user.id,
                    )
                )
                == 0
            )
            await commands.approve(user.id, card.id, card.version)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Workout)
                    .where(
                        Workout.user_id == user.id,
                    )
                )
                == 1
            )
            sets = list(
                await session.scalars(
                    select(WorkoutSet)
                    .join(Workout)
                    .where(
                        Workout.user_id == user.id,
                    )
                )
            )
            assert len(sets) == 4
            assert all(row.weight_kg == 30 and row.reps == 12 for row in sets)
        finally:
            await session.rollback()
