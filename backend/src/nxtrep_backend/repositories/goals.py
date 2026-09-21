from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Exercise, User, UserConstraint, UserGoal


@dataclass(frozen=True, slots=True)
class GoalsState:
    goal: UserGoal | None
    constraints: UserConstraint | None


class SqlAlchemyGoalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_state(
        self,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> GoalsState:
        if for_update:
            await self._lock_user(user_id)

        goal_statement = select(UserGoal).where(
            UserGoal.user_id == user_id,
            UserGoal.status == "active",
        )
        constraints_statement = select(UserConstraint).where(
            UserConstraint.user_id == user_id,
        )

        if for_update:
            goal_statement = goal_statement.with_for_update()
            constraints_statement = constraints_statement.with_for_update()

        goal = await self._session.scalar(goal_statement)
        constraints = await self._session.scalar(constraints_statement)

        return GoalsState(
            goal=goal,
            constraints=constraints,
        )

    async def save_new_version(
        self,
        *,
        goal: UserGoal,
        constraints: UserConstraint,
    ) -> None:
        self._session.add_all([goal, constraints])
        await self._session.flush()

    async def list_goals(self, user_id: UUID) -> list[UserGoal]:
        return list(
            await self._session.scalars(
                select(UserGoal)
                .where(UserGoal.user_id == user_id)
                .order_by(UserGoal.version.desc())
            )
        )

    async def visible_exercise_ids(self, user_id: UUID, exercise_ids: set[UUID]) -> set[UUID]:
        if not exercise_ids:
            return set()
        return set(
            await self._session.scalars(
                select(Exercise.id).where(
                    Exercise.id.in_(exercise_ids),
                    Exercise.deleted_at.is_(None),
                    (Exercise.owner_user_id.is_(None) | (Exercise.owner_user_id == user_id)),
                )
            )
        )

    async def _lock_user(self, user_id: UUID) -> None:
        statement = select(User.id).where(User.id == user_id).with_for_update()
        await self._session.scalar(statement)
