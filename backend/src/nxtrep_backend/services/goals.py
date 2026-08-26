from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from nxtrep_backend.db.models import GoalStatus, UserConstraint, UserGoal
from nxtrep_backend.repositories.goals import SqlAlchemyGoalsRepository


@dataclass(frozen=True, slots=True)
class GoalsUpdateData:
    goal_type: str
    target_date: date | None
    target_weight_kg: Decimal | None
    equipment: list[str]
    preferred_exercises: list[UUID]
    disliked_exercises: list[UUID]
    pain_or_injuries: list[dict[str, Any]]
    allergies: list[str]
    dietary_preferences: list[str]


@dataclass(frozen=True, slots=True)
class GoalsUpdateResult:
    goal: UserGoal
    constraints: UserConstraint
    warnings: list[str]


class GoalsVersionRequiredError(RuntimeError):
    """已有目标时，客户端必须提供 expected_version。"""


class GoalsVersionConflictError(RuntimeError):
    """客户端提交的目标版本已经过期。"""

    def __init__(
        self,
        *,
        expected_version: int,
        current_version: int,
    ) -> None:
        super().__init__("Goals version conflict")
        self.expected_version = expected_version
        self.current_version = current_version


class GoalsStateError(RuntimeError):
    """目标和限制的数据库状态不一致。"""


class GoalsNotFoundError(RuntimeError):
    """当前用户还没有设置目标和限制。"""


class GoalsExerciseUnavailableError(RuntimeError):
    """偏好或排除列表引用了当前用户不可见的动作。"""

    def __init__(self, exercise_ids: set[UUID]) -> None:
        super().__init__("One or more exercises are unavailable")
        self.exercise_ids = exercise_ids


class GoalsService:
    def __init__(
        self,
        repository: SqlAlchemyGoalsRepository,
    ) -> None:
        self._repository = repository

    async def update_goals_and_constraints(
        self,
        *,
        user_id: UUID,
        data: GoalsUpdateData,
        expected_version: int | None,
    ) -> GoalsUpdateResult:
        requested_exercises = set(data.preferred_exercises) | set(data.disliked_exercises)
        if requested_exercises:
            visible = await self._repository.visible_exercise_ids(user_id, requested_exercises)
            if missing := requested_exercises - visible:
                raise GoalsExerciseUnavailableError(missing)
        state = await self._repository.get_state(
            user_id,
            for_update=True,
        )

        if (state.goal is None) != (state.constraints is None):
            raise GoalsStateError("Goal and constraints must exist together")

        if (
            state.goal is not None
            and state.constraints is not None
            and state.goal.version != state.constraints.version
        ):
            raise GoalsStateError("Goal and constraints versions do not match")

        if state.goal is None:
            if expected_version is not None:
                raise GoalsVersionConflictError(
                    expected_version=expected_version,
                    current_version=0,
                )

            current_version = 0
        else:
            current_version = state.goal.version

            if expected_version is None:
                raise GoalsVersionRequiredError("expected_version is required")

            if expected_version != current_version:
                raise GoalsVersionConflictError(
                    expected_version=expected_version,
                    current_version=current_version,
                )

            state.goal.status = GoalStatus.SUPERSEDED.value

        new_version = current_version + 1

        goal = UserGoal(
            user_id=user_id,
            goal_type=data.goal_type,
            target_date=data.target_date,
            target_weight_kg=data.target_weight_kg,
            status=GoalStatus.ACTIVE.value,
            version=new_version,
        )

        if state.constraints is None:
            constraints = UserConstraint(
                user_id=user_id,
            )
        else:
            constraints = state.constraints

        constraints.equipment = list(data.equipment)
        constraints.preferred_exercise_ids = [
            str(exercise_id) for exercise_id in data.preferred_exercises
        ]
        constraints.disliked_exercise_ids = [
            str(exercise_id) for exercise_id in data.disliked_exercises
        ]
        constraints.pain_or_injuries = list(data.pain_or_injuries)
        constraints.allergies = list(data.allergies)
        constraints.dietary_preferences = list(data.dietary_preferences)
        constraints.version = new_version

        await self._repository.save_new_version(
            goal=goal,
            constraints=constraints,
        )

        return GoalsUpdateResult(
            goal=goal,
            constraints=constraints,
            warnings=self._build_warnings(
                goal_type=goal.goal_type,
                target_date=goal.target_date,
                equipment=constraints.equipment,
            ),
        )

    async def get_goals_and_constraints(
        self,
        *,
        user_id: UUID,
    ) -> GoalsUpdateResult:
        state = await self._repository.get_state(
            user_id,
        )

        if state.goal is None and state.constraints is None:
            raise GoalsNotFoundError("Goals and constraints not found")

        if state.goal is None or state.constraints is None:
            raise GoalsStateError("Goal and constraints must exist together")

        if state.goal.version != state.constraints.version:
            raise GoalsStateError("Goal and constraints versions do not match")

        return GoalsUpdateResult(
            goal=state.goal,
            constraints=state.constraints,
            warnings=self._build_warnings(
                goal_type=state.goal.goal_type,
                target_date=state.goal.target_date,
                equipment=state.constraints.equipment,
            ),
        )

    @staticmethod
    def _build_warnings(
        *,
        goal_type: str,
        target_date: date | None,
        equipment: list[str],
    ) -> list[str]:
        warnings: list[str] = []

        if goal_type == "strength" and not equipment:
            warnings.append("STRENGTH_GOAL_WITHOUT_EQUIPMENT")

        short_timeline_goal_types = {
            "muscle_gain",
            "fat_loss_retain",
            "recomposition",
        }

        if (
            target_date is not None
            and goal_type in short_timeline_goal_types
            and target_date < date.today() + timedelta(days=28)
        ):
            warnings.append("TARGET_TIMELINE_MAY_BE_TOO_SHORT")

        return warnings
