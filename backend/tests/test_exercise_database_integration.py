import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import (
    Exercise,
    ExerciseAlias,
    ExerciseMuscle,
    ExerciseSubstitution,
    User,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_list_exercises_enforces_visibility_and_filters_in_real_database() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            current_user = User(
                username=f"exercise-current-{uuid4().hex}",
                password_setup_required=False,
            )
            other_user = User(
                username=f"exercise-other-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add_all([current_user, other_user])
            await session.flush()

            official = Exercise(
                owner_user_id=None,
                name_zh="集成测试杠铃深蹲",
                equipment="barbell",
            )
            own_custom = Exercise(
                owner_user_id=current_user.id,
                name_zh="集成测试高脚杯深蹲",
                equipment="dumbbell",
            )
            other_custom = Exercise(
                owner_user_id=other_user.id,
                name_zh="集成测试他人深蹲",
                equipment="barbell",
            )
            deleted = Exercise(
                owner_user_id=current_user.id,
                name_zh="集成测试已删除深蹲",
                equipment="barbell",
                deleted_at=datetime.now(UTC),
            )
            session.add_all([official, own_custom, other_custom, deleted])
            await session.flush()

            session.add_all(
                [
                    ExerciseAlias(
                        exercise_id=official.id,
                        alias="集成别名深蹲",
                        normalized_alias="集成别名深蹲",
                    ),
                    ExerciseMuscle(
                        exercise_id=official.id,
                        muscle_code="quadriceps",
                        role="primary",
                    ),
                    ExerciseMuscle(
                        exercise_id=own_custom.id,
                        muscle_code="quadriceps",
                        role="primary",
                    ),
                    ExerciseMuscle(
                        exercise_id=official.id,
                        muscle_code="hamstring",
                        role="secondary",
                    ),
                    ExerciseSubstitution(
                        source_exercise_id=official.id,
                        target_exercise_id=own_custom.id,
                        reason="当前用户可见",
                        priority=1,
                    ),
                    ExerciseSubstitution(
                        source_exercise_id=official.id,
                        target_exercise_id=other_custom.id,
                        reason="他人动作不可见",
                        priority=2,
                    ),
                    ExerciseSubstitution(
                        source_exercise_id=official.id,
                        target_exercise_id=deleted.id,
                        reason="已删除动作不可见",
                        priority=3,
                    ),
                ]
            )
            await session.flush()

            repository = SqlAlchemyExercisesRepository(session)
            visible = await repository.list_exercises(
                user_id=current_user.id,
                keyword="集成测试",
                equipment=None,
                muscle=None,
                page=1,
                page_size=20,
            )
            alias_match = await repository.list_exercises(
                user_id=current_user.id,
                keyword="集成别名",
                equipment="barbell",
                muscle="quadriceps",
                page=1,
                page_size=20,
            )
            detail = await repository.get_exercise_detail(
                user_id=current_user.id,
                exercise_id=official.id,
            )
            hidden_detail = await repository.get_exercise_detail(
                user_id=current_user.id,
                exercise_id=other_custom.id,
            )
            deleted_detail = await repository.get_exercise_detail(
                user_id=current_user.id,
                exercise_id=deleted.id,
            )

            assert {item.exercise.id for item in visible.items} == {
                official.id,
                own_custom.id,
            }
            assert visible.total == 2
            assert [item.exercise.id for item in alias_match.items] == [official.id]
            assert alias_match.items[0].aliases == ["集成别名深蹲"]
            assert alias_match.items[0].primary_muscles == ["quadriceps"]
            assert detail is not None
            assert detail.aliases == ["集成别名深蹲"]
            assert detail.primary_muscles == ["quadriceps"]
            assert detail.secondary_muscles == ["hamstring"]
            assert [item.exercise.id for item in detail.substitutions] == [own_custom.id]
            assert detail.substitutions[0].reason == "当前用户可见"
            assert hidden_detail is None
            assert deleted_detail is None
        finally:
            await transaction.rollback()
