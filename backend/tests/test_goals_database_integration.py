import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from nxtrep_backend.db.models import User, UserConstraint, UserGoal
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.goals import SqlAlchemyGoalsRepository
from nxtrep_backend.services.goals import GoalsService, GoalsUpdateData

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


def make_data(goal_type: str, equipment: list[str]) -> GoalsUpdateData:
    return GoalsUpdateData(
        goal_type=goal_type,
        target_date=None,
        target_weight_kg=Decimal("72.500"),
        equipment=equipment,
        preferred_exercises=[],
        disliked_exercises=[],
        pain_or_injuries=[],
        allergies=[],
        dietary_preferences=[],
    )


@pytest.mark.asyncio
async def test_create_and_replace_goals_in_real_database() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            user = User(
                username=f"integration-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add(user)
            await session.flush()

            repository = SqlAlchemyGoalsRepository(session)
            service = GoalsService(repository)

            first = await service.update_goals_and_constraints(
                user_id=user.id,
                data=make_data("muscle_gain", ["dumbbell"]),
                expected_version=None,
            )
            second = await service.update_goals_and_constraints(
                user_id=user.id,
                data=make_data("strength", ["barbell"]),
                expected_version=first.goal.version,
            )

            goals = list(
                (
                    await session.scalars(
                        select(UserGoal)
                        .where(UserGoal.user_id == user.id)
                        .order_by(UserGoal.version)
                    )
                ).all()
            )
            constraints = await session.get(UserConstraint, user.id)

            assert [(goal.version, goal.status) for goal in goals] == [
                (1, "superseded"),
                (2, "active"),
            ]
            assert second.goal.version == 2
            assert constraints is not None
            assert constraints.version == 2
            assert constraints.equipment == ["barbell"]
        finally:
            await transaction.rollback()
