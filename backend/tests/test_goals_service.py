from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import UserConstraint, UserGoal
from nxtrep_backend.repositories.goals import GoalsState, SqlAlchemyGoalsRepository
from nxtrep_backend.services.goals import (
    GoalsNotFoundError,
    GoalsService,
    GoalsStateError,
    GoalsUpdateData,
    GoalsVersionConflictError,
    GoalsVersionRequiredError,
)


def make_data(**changes: object) -> GoalsUpdateData:
    values: dict[str, object] = {
        "goal_type": "muscle_gain",
        "target_date": None,
        "target_weight_kg": Decimal("72.500"),
        "equipment": ["barbell", "dumbbell"],
        "preferred_exercises": [],
        "disliked_exercises": [],
        "pain_or_injuries": [],
        "allergies": ["peanut"],
        "dietary_preferences": [],
    }
    values.update(changes)
    return GoalsUpdateData(**values)


def make_repository(state: GoalsState) -> MagicMock:
    repository = MagicMock(spec=SqlAlchemyGoalsRepository)
    repository.get_state = AsyncMock(return_value=state)
    repository.save_new_version = AsyncMock()
    return repository


@pytest.mark.asyncio
async def test_create_initial_goals_and_constraints() -> None:
    user_id = uuid4()
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    result = await service.update_goals_and_constraints(
        user_id=user_id,
        data=make_data(),
        expected_version=None,
    )

    assert result.goal.user_id == user_id
    assert result.goal.goal_type == "muscle_gain"
    assert result.goal.status == "active"
    assert result.goal.version == 1
    assert result.constraints.user_id == user_id
    assert result.constraints.equipment == ["barbell", "dumbbell"]
    assert result.constraints.allergies == ["peanut"]
    assert result.constraints.version == 1
    assert result.warnings == []
    repository.get_state.assert_awaited_once_with(user_id, for_update=True)
    repository.save_new_version.assert_awaited_once_with(
        goal=result.goal,
        constraints=result.constraints,
    )


@pytest.mark.asyncio
async def test_update_creates_new_goal_and_reuses_constraints() -> None:
    user_id = uuid4()
    preferred_exercise_id = uuid4()
    old_goal = UserGoal(
        user_id=user_id,
        goal_type="muscle_gain",
        status="active",
        version=1,
    )
    constraints = UserConstraint(
        user_id=user_id,
        equipment=["dumbbell"],
        preferred_exercise_ids=[],
        disliked_exercise_ids=[],
        pain_or_injuries=[],
        allergies=[],
        dietary_preferences=[],
        version=1,
    )
    repository = make_repository(GoalsState(goal=old_goal, constraints=constraints))
    service = GoalsService(repository)

    result = await service.update_goals_and_constraints(
        user_id=user_id,
        data=make_data(
            goal_type="strength",
            equipment=["barbell"],
            preferred_exercises=[preferred_exercise_id],
        ),
        expected_version=1,
    )

    assert old_goal.status == "superseded"
    assert result.goal is not old_goal
    assert result.goal.goal_type == "strength"
    assert result.goal.status == "active"
    assert result.goal.version == 2
    assert result.constraints is constraints
    assert constraints.equipment == ["barbell"]
    assert constraints.preferred_exercise_ids == [str(preferred_exercise_id)]
    assert constraints.version == 2


@pytest.mark.asyncio
async def test_update_requires_expected_version() -> None:
    user_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="maintain",
        status="active",
        version=2,
    )
    constraints = UserConstraint(
        user_id=user_id,
        equipment=["barbell"],
        version=2,
    )
    repository = make_repository(GoalsState(goal=goal, constraints=constraints))
    service = GoalsService(repository)

    with pytest.raises(GoalsVersionRequiredError):
        await service.update_goals_and_constraints(
            user_id=user_id,
            data=make_data(),
            expected_version=None,
        )

    assert goal.status == "active"
    repository.save_new_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_reports_version_conflict_without_mutating_state() -> None:
    user_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="maintain",
        status="active",
        version=3,
    )
    constraints = UserConstraint(user_id=user_id, version=3)
    repository = make_repository(GoalsState(goal=goal, constraints=constraints))
    service = GoalsService(repository)

    with pytest.raises(GoalsVersionConflictError) as error:
        await service.update_goals_and_constraints(
            user_id=user_id,
            data=make_data(),
            expected_version=2,
        )

    assert error.value.expected_version == 2
    assert error.value.current_version == 3
    assert goal.status == "active"
    repository.save_new_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_create_rejects_unexpected_existing_version() -> None:
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    with pytest.raises(GoalsVersionConflictError) as error:
        await service.update_goals_and_constraints(
            user_id=uuid4(),
            data=make_data(),
            expected_version=1,
        )

    assert error.value.current_version == 0
    repository.save_new_version.assert_not_awaited()


@pytest.mark.parametrize(
    ("state"),
    [
        GoalsState(
            goal=UserGoal(
                user_id=uuid4(),
                goal_type="strength",
                status="active",
                version=1,
            ),
            constraints=None,
        ),
        GoalsState(
            goal=None,
            constraints=UserConstraint(user_id=uuid4(), version=1),
        ),
    ],
)
@pytest.mark.asyncio
async def test_rejects_partially_missing_database_state(state: GoalsState) -> None:
    repository = make_repository(state)
    service = GoalsService(repository)

    with pytest.raises(GoalsStateError):
        await service.update_goals_and_constraints(
            user_id=uuid4(),
            data=make_data(),
            expected_version=1,
        )

    repository.save_new_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_mismatched_goal_and_constraints_versions() -> None:
    user_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="strength",
        status="active",
        version=2,
    )
    constraints = UserConstraint(user_id=user_id, version=1)
    repository = make_repository(GoalsState(goal=goal, constraints=constraints))
    service = GoalsService(repository)

    with pytest.raises(GoalsStateError):
        await service.update_goals_and_constraints(
            user_id=user_id,
            data=make_data(),
            expected_version=2,
        )

    repository.save_new_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_goals_and_constraints_returns_current_state() -> None:
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
    repository = make_repository(GoalsState(goal=goal, constraints=constraints))
    service = GoalsService(repository)

    result = await service.get_goals_and_constraints(user_id=user_id)

    assert result.goal is goal
    assert result.constraints is constraints
    assert result.warnings == []
    repository.get_state.assert_awaited_once_with(user_id)
    repository.save_new_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_goals_and_constraints_reports_not_found() -> None:
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    with pytest.raises(GoalsNotFoundError):
        await service.get_goals_and_constraints(user_id=uuid4())


@pytest.mark.asyncio
async def test_get_goals_and_constraints_rejects_partial_state() -> None:
    user_id = uuid4()
    repository = make_repository(
        GoalsState(
            goal=UserGoal(
                user_id=user_id,
                goal_type="maintain",
                status="active",
                version=1,
            ),
            constraints=None,
        )
    )
    service = GoalsService(repository)

    with pytest.raises(GoalsStateError):
        await service.get_goals_and_constraints(user_id=user_id)


@pytest.mark.asyncio
async def test_get_goals_and_constraints_rejects_mismatched_versions() -> None:
    user_id = uuid4()
    repository = make_repository(
        GoalsState(
            goal=UserGoal(
                user_id=user_id,
                goal_type="maintain",
                status="active",
                version=2,
            ),
            constraints=UserConstraint(user_id=user_id, version=1),
        )
    )
    service = GoalsService(repository)

    with pytest.raises(GoalsStateError):
        await service.get_goals_and_constraints(user_id=user_id)


@pytest.mark.asyncio
async def test_strength_goal_without_equipment_returns_warning() -> None:
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    result = await service.update_goals_and_constraints(
        user_id=uuid4(),
        data=make_data(goal_type="strength", equipment=[]),
        expected_version=None,
    )

    assert result.warnings == ["STRENGTH_GOAL_WITHOUT_EQUIPMENT"]


@pytest.mark.asyncio
async def test_short_target_timeline_returns_warning() -> None:
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    result = await service.update_goals_and_constraints(
        user_id=uuid4(),
        data=make_data(target_date=date.today() + timedelta(days=27)),
        expected_version=None,
    )

    assert result.warnings == ["TARGET_TIMELINE_MAY_BE_TOO_SHORT"]


@pytest.mark.asyncio
async def test_target_timeline_boundary_does_not_return_warning() -> None:
    repository = make_repository(GoalsState(goal=None, constraints=None))
    service = GoalsService(repository)

    result = await service.update_goals_and_constraints(
        user_id=uuid4(),
        data=make_data(target_date=date.today() + timedelta(days=28)),
        expected_version=None,
    )

    assert result.warnings == []


@pytest.mark.asyncio
async def test_get_goals_rebuilds_warnings_from_current_state() -> None:
    user_id = uuid4()
    repository = make_repository(
        GoalsState(
            goal=UserGoal(
                user_id=user_id,
                goal_type="strength",
                status="active",
                version=1,
            ),
            constraints=UserConstraint(
                user_id=user_id,
                equipment=[],
                version=1,
            ),
        )
    )
    service = GoalsService(repository)

    result = await service.get_goals_and_constraints(user_id=user_id)

    assert result.warnings == ["STRENGTH_GOAL_WITHOUT_EQUIPMENT"]
