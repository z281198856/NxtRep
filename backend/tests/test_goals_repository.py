from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import UserConstraint, UserGoal
from nxtrep_backend.repositories.goals import SqlAlchemyGoalsRepository


def compile_statement(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_get_state_can_lock_user_goal_and_constraints() -> None:
    user_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="strength",
        status="active",
        version=2,
    )
    constraints = UserConstraint(
        user_id=user_id,
        equipment=["barbell"],
        version=2,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[user_id, goal, constraints])
    repository = SqlAlchemyGoalsRepository(session)

    state = await repository.get_state(user_id, for_update=True)

    assert state.goal is goal
    assert state.constraints is constraints
    statements = [compile_statement(call.args[0]) for call in session.scalar.await_args_list]
    assert "FROM users" in statements[0]
    assert "FOR UPDATE" in statements[0]
    assert "user_goals.status = 'active'" in statements[1]
    assert "FOR UPDATE" in statements[1]
    assert "FROM user_constraints" in statements[2]
    assert "FOR UPDATE" in statements[2]


@pytest.mark.asyncio
async def test_get_state_without_lock_only_queries_goal_and_constraints() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[None, None])
    repository = SqlAlchemyGoalsRepository(session)

    state = await repository.get_state(uuid4())

    assert state.goal is None
    assert state.constraints is None
    assert session.scalar.await_count == 2
    assert all(
        "FOR UPDATE" not in compile_statement(call.args[0])
        for call in session.scalar.await_args_list
    )


@pytest.mark.asyncio
async def test_save_new_version_adds_entities_and_flushes() -> None:
    user_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="maintain",
        status="active",
        version=1,
    )
    constraints = UserConstraint(
        user_id=user_id,
        equipment=[],
        version=1,
    )
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyGoalsRepository(session)

    await repository.save_new_version(
        goal=goal,
        constraints=constraints,
    )

    session.add_all.assert_called_once_with([goal, constraints])
    session.flush.assert_awaited_once_with()
