import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import Exercise, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
from nxtrep_backend.repositories.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from nxtrep_backend.services.exercise import ExerciseCreateData, ExercisesService
from nxtrep_backend.services.idempotency import (
    IdempotencyKeyConflictError,
    IdempotencyService,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_idempotent_exercise_create_executes_once_in_real_database() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            user = User(
                username=f"idempotent-exercise-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add(user)
            await session.flush()

            exercise_service = ExercisesService(SqlAlchemyExercisesRepository(session))
            idempotency_service = IdempotencyService(SqlAlchemyIdempotencyRepository(session))
            idempotency_key = uuid4()
            payload = {
                "name_zh": "幂等集成测试深蹲",
                "equipment": "dumbbell",
                "primary_muscles": ["quadriceps"],
                "secondary_muscles": [],
                "notes": None,
            }

            first_decision = await idempotency_service.begin(
                user_id=user.id,
                idempotency_key=idempotency_key,
                operation="POST /exercises",
                payload=payload,
            )
            created = await exercise_service.create_custom_exercise(
                user_id=user.id,
                data=ExerciseCreateData(**payload),
            )
            stored_response = {
                "id": str(created.exercise.id),
                "name_zh": created.exercise.name_zh,
            }
            await idempotency_service.complete(
                decision=first_decision,
                response_status=201,
                response_body=stored_response,
            )

            replay = await idempotency_service.begin(
                user_id=user.id,
                idempotency_key=idempotency_key,
                operation="POST /exercises",
                payload=payload,
            )
            exercise_count = await session.scalar(
                select(func.count()).select_from(Exercise).where(Exercise.owner_user_id == user.id)
            )

            assert first_decision.replayed is False
            assert replay.replayed is True
            assert replay.response_status == 201
            assert replay.response_body == stored_response
            assert exercise_count == 1

            with pytest.raises(IdempotencyKeyConflictError):
                await idempotency_service.begin(
                    user_id=user.id,
                    idempotency_key=idempotency_key,
                    operation="POST /exercises",
                    payload={**payload, "name_zh": "不同动作"},
                )
        finally:
            await transaction.rollback()
