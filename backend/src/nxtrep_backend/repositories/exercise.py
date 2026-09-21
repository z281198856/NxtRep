from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    Exercise,
    ExerciseAlias,
    ExerciseContentFeedback,
    ExerciseMedia,
    ExerciseMuscle,
    ExerciseSubstitution,
)


@dataclass(frozen=True, slots=True)
class ExerciseListEntry:
    exercise: Exercise
    aliases: list[str]
    primary_muscles: list[str]


@dataclass(frozen=True, slots=True)
class ExercisePage:
    items: list[ExerciseListEntry]
    total: int


@dataclass(frozen=True, slots=True)
class ExerciseSubstitutionEntry:
    exercise: Exercise
    reason: str


@dataclass(frozen=True, slots=True)
class ExerciseDetailRecord:
    exercise: Exercise
    aliases: list[str]
    primary_muscles: list[str]
    secondary_muscles: list[str]
    substitutions: list[ExerciseSubstitutionEntry]


@dataclass(frozen=True, slots=True)
class ExerciseUpdateState:
    exercise: Exercise
    primary_muscles: list[str]
    secondary_muscles: list[str]


class SqlAlchemyExercisesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_feedback(self, item: ExerciseContentFeedback) -> ExerciseContentFeedback:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_media_for_user(
        self,
        *,
        user_id: UUID,
        media_id: UUID,
    ) -> ExerciseMedia | None:
        return await self._session.scalar(
            select(ExerciseMedia)
            .join(Exercise, Exercise.id == ExerciseMedia.exercise_id)
            .where(
                ExerciseMedia.id == media_id,
                Exercise.deleted_at.is_(None),
                or_(Exercise.owner_user_id.is_(None), Exercise.owner_user_id == user_id),
            )
        )

    async def list_exercises(
        self,
        *,
        user_id: UUID,
        keyword: str | None,
        equipment: str | None,
        muscle: str | None,
        page: int,
        page_size: int,
    ) -> ExercisePage:
        conditions = [
            Exercise.deleted_at.is_(None),
            or_(
                Exercise.owner_user_id.is_(None),
                Exercise.owner_user_id == user_id,
            ),
        ]

        if keyword is not None:
            pattern = f"%{self._escape_like(keyword)}%"
            conditions.append(
                or_(
                    Exercise.name_zh.ilike(pattern, escape="\\"),
                    exists(
                        select(1).where(
                            ExerciseAlias.exercise_id == Exercise.id,
                            ExerciseAlias.normalized_alias.ilike(
                                pattern,
                                escape="\\",
                            ),
                        )
                    ),
                )
            )

        if equipment is not None:
            conditions.append(Exercise.equipment == equipment)

        if muscle is not None:
            conditions.append(
                exists(
                    select(1).where(
                        ExerciseMuscle.exercise_id == Exercise.id,
                        ExerciseMuscle.muscle_code == muscle,
                    )
                )
            )

        total_statement = select(func.count()).select_from(Exercise).where(*conditions)
        total = int(await self._session.scalar(total_statement) or 0)

        statement = (
            select(Exercise)
            .where(*conditions)
            .order_by(Exercise.name_zh, Exercise.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        exercises = list((await self._session.scalars(statement)).all())

        if not exercises:
            return ExercisePage(items=[], total=total)

        exercise_ids = [exercise.id for exercise in exercises]

        alias_statement = (
            select(
                ExerciseAlias.exercise_id,
                ExerciseAlias.alias,
            )
            .where(ExerciseAlias.exercise_id.in_(exercise_ids))
            .order_by(
                ExerciseAlias.exercise_id,
                ExerciseAlias.alias,
            )
        )
        alias_rows = (await self._session.execute(alias_statement)).all()

        muscle_statement = (
            select(
                ExerciseMuscle.exercise_id,
                ExerciseMuscle.muscle_code,
            )
            .where(
                ExerciseMuscle.exercise_id.in_(exercise_ids),
                ExerciseMuscle.role == "primary",
            )
            .order_by(
                ExerciseMuscle.exercise_id,
                ExerciseMuscle.muscle_code,
            )
        )
        muscle_rows = (await self._session.execute(muscle_statement)).all()

        aliases_by_exercise: defaultdict[UUID, list[str]] = defaultdict(list)
        for exercise_id, alias in alias_rows:
            aliases_by_exercise[exercise_id].append(alias)

        muscles_by_exercise: defaultdict[UUID, list[str]] = defaultdict(list)
        for exercise_id, muscle_code in muscle_rows:
            muscles_by_exercise[exercise_id].append(muscle_code)

        items = [
            ExerciseListEntry(
                exercise=exercise,
                aliases=aliases_by_exercise[exercise.id],
                primary_muscles=muscles_by_exercise[exercise.id],
            )
            for exercise in exercises
        ]

        return ExercisePage(items=items, total=total)

    async def get_exercise_detail(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
    ) -> ExerciseDetailRecord | None:
        statement = select(Exercise).where(
            Exercise.id == exercise_id,
            Exercise.deleted_at.is_(None),
            or_(
                Exercise.owner_user_id.is_(None),
                Exercise.owner_user_id == user_id,
            ),
        )
        exercise = await self._session.scalar(statement)

        if exercise is None:
            return None

        alias_statement = (
            select(ExerciseAlias.alias)
            .where(ExerciseAlias.exercise_id == exercise.id)
            .order_by(ExerciseAlias.alias)
        )
        aliases = list((await self._session.scalars(alias_statement)).all())

        muscle_statement = (
            select(
                ExerciseMuscle.role,
                ExerciseMuscle.muscle_code,
            )
            .where(ExerciseMuscle.exercise_id == exercise.id)
            .order_by(
                ExerciseMuscle.role,
                ExerciseMuscle.muscle_code,
            )
        )
        muscle_rows = (await self._session.execute(muscle_statement)).all()

        primary_muscles = [muscle_code for role, muscle_code in muscle_rows if role == "primary"]
        secondary_muscles = [
            muscle_code for role, muscle_code in muscle_rows if role == "secondary"
        ]

        substitution_statement = (
            select(
                Exercise,
                ExerciseSubstitution.reason,
            )
            .select_from(ExerciseSubstitution)
            .join(
                Exercise,
                Exercise.id == ExerciseSubstitution.target_exercise_id,
            )
            .where(
                ExerciseSubstitution.source_exercise_id == exercise.id,
                Exercise.deleted_at.is_(None),
                or_(
                    Exercise.owner_user_id.is_(None),
                    Exercise.owner_user_id == user_id,
                ),
            )
            .order_by(
                ExerciseSubstitution.priority,
                Exercise.name_zh,
                Exercise.id,
            )
        )
        substitution_rows = (await self._session.execute(substitution_statement)).all()

        substitutions = [
            ExerciseSubstitutionEntry(
                exercise=target,
                reason=reason,
            )
            for target, reason in substitution_rows
        ]

        return ExerciseDetailRecord(
            exercise=exercise,
            aliases=aliases,
            primary_muscles=primary_muscles,
            secondary_muscles=secondary_muscles,
            substitutions=substitutions,
        )

    async def save_custom_exercise(
        self,
        *,
        exercise: Exercise,
        muscles: list[ExerciseMuscle],
    ) -> None:
        self._session.add(exercise)
        self._session.add_all(muscles)
        await self._session.flush()

    async def get_custom_exercise_for_update(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
    ) -> ExerciseUpdateState | None:
        statement = (
            select(Exercise)
            .where(
                Exercise.id == exercise_id,
                Exercise.owner_user_id == user_id,
                Exercise.deleted_at.is_(None),
            )
            .with_for_update()
        )
        exercise = await self._session.scalar(statement)

        if exercise is None:
            return None

        muscle_statement = (
            select(
                ExerciseMuscle.role,
                ExerciseMuscle.muscle_code,
            )
            .where(ExerciseMuscle.exercise_id == exercise.id)
            .order_by(
                ExerciseMuscle.role,
                ExerciseMuscle.muscle_code,
            )
        )
        muscle_rows = (await self._session.execute(muscle_statement)).all()

        return ExerciseUpdateState(
            exercise=exercise,
            primary_muscles=[muscle_code for role, muscle_code in muscle_rows if role == "primary"],
            secondary_muscles=[
                muscle_code for role, muscle_code in muscle_rows if role == "secondary"
            ],
        )

    async def save_custom_exercise_update(
        self,
        *,
        exercise: Exercise,
        muscles: list[ExerciseMuscle] | None,
    ) -> None:
        if muscles is not None:
            delete_statement = delete(ExerciseMuscle).where(
                ExerciseMuscle.exercise_id == exercise.id
            )
            await self._session.execute(delete_statement)
            self._session.add_all(muscles)

        await self._session.flush()

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
