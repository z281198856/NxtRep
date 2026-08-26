from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    Exercise,
    PersonalRecord,
    ProgressionDraft,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutSetRevision,
)


@dataclass(slots=True)
class WorkoutAggregate:
    workout: Workout
    exercises: list[WorkoutExercise]
    sets_by_exercise: dict[UUID, list[WorkoutSet]]


class SqlAlchemyWorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, user_id: UUID) -> Workout | None:
        return await self.session.scalar(
            select(Workout).where(Workout.user_id == user_id, Workout.status == "in_progress")
        )

    async def add_workout(self, workout: Workout, exercises: list[WorkoutExercise]) -> None:
        self.session.add(workout)
        await self.session.flush()
        for item in exercises:
            item.workout_id = workout.id
        self.session.add_all(exercises)
        await self.session.flush()

    async def get_workout(
        self, user_id: UUID, workout_id: UUID, *, lock: bool = False
    ) -> Workout | None:
        statement = select(Workout).where(Workout.id == workout_id, Workout.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_aggregate(self, user_id: UUID, workout_id: UUID) -> WorkoutAggregate | None:
        workout = await self.get_workout(user_id, workout_id)
        if workout is None:
            return None
        exercises = list(
            await self.session.scalars(
                select(WorkoutExercise)
                .where(WorkoutExercise.workout_id == workout.id)
                .order_by(WorkoutExercise.order_no)
            )
        )
        sets = list(
            await self.session.scalars(
                select(WorkoutSet)
                .where(WorkoutSet.workout_id == workout.id)
                .order_by(WorkoutSet.workout_exercise_id, WorkoutSet.set_index)
            )
        )
        grouped: dict[UUID, list[WorkoutSet]] = {item.id: [] for item in exercises}
        for item in sets:
            grouped.setdefault(item.workout_exercise_id, []).append(item)
        return WorkoutAggregate(workout, exercises, grouped)

    async def list_workouts(
        self,
        user_id: UUID,
        start_date: date | None,
        end_date: date | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Workout], int]:
        conditions = [Workout.user_id == user_id]
        if start_date:
            conditions.append(func.date(Workout.started_at) >= start_date)
        if end_date:
            conditions.append(func.date(Workout.started_at) <= end_date)
        if status:
            conditions.append(Workout.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(Workout).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(Workout)
                .where(*conditions)
                .order_by(Workout.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_workout_exercise(
        self, workout_id: UUID, item_id: UUID, *, lock: bool = False
    ) -> WorkoutExercise | None:
        statement = select(WorkoutExercise).where(
            WorkoutExercise.id == item_id, WorkoutExercise.workout_id == workout_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_exercise(self, user_id: UUID, exercise_id: UUID) -> Exercise | None:
        return await self.session.scalar(
            select(Exercise).where(
                Exercise.id == exercise_id,
                Exercise.deleted_at.is_(None),
                (Exercise.owner_user_id.is_(None) | (Exercise.owner_user_id == user_id)),
            )
        )

    async def get_set(
        self, workout_id: UUID, set_id: UUID, *, lock: bool = False
    ) -> WorkoutSet | None:
        statement = select(WorkoutSet).where(
            WorkoutSet.id == set_id, WorkoutSet.workout_id == workout_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_set_by_client_id(self, workout_id: UUID, client_id: UUID) -> WorkoutSet | None:
        return await self.session.scalar(
            select(WorkoutSet).where(
                WorkoutSet.workout_id == workout_id,
                WorkoutSet.client_generated_id == client_id,
            )
        )

    async def get_set_by_index(
        self, workout_exercise_id: UUID, set_index: int
    ) -> WorkoutSet | None:
        return await self.session.scalar(
            select(WorkoutSet).where(
                WorkoutSet.workout_exercise_id == workout_exercise_id,
                WorkoutSet.set_index == set_index,
            )
        )

    async def add_set(self, item: WorkoutSet) -> WorkoutSet:
        self.session.add(item)
        await self.session.flush()
        return item

    async def add_set_revision(self, revision: WorkoutSetRevision) -> None:
        self.session.add(revision)
        await self.session.flush()

    async def list_sets(self, workout_id: UUID) -> list[WorkoutSet]:
        return list(
            await self.session.scalars(
                select(WorkoutSet).where(WorkoutSet.workout_id == workout_id)
            )
        )

    async def add_progression_draft(self, draft: ProgressionDraft) -> ProgressionDraft:
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def get_progression_draft(
        self, user_id: UUID, workout_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> ProgressionDraft | None:
        statement = select(ProgressionDraft).where(
            ProgressionDraft.id == draft_id,
            ProgressionDraft.user_id == user_id,
            ProgressionDraft.workout_id == workout_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_progression_draft_by_id(
        self, user_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> ProgressionDraft | None:
        statement = select(ProgressionDraft).where(
            ProgressionDraft.id == draft_id, ProgressionDraft.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def add_records(self, records: list[PersonalRecord]) -> None:
        self.session.add_all(records)
        await self.session.flush()

    async def best_record(self, user_id: UUID, exercise_id: UUID, record_type: str):
        return await self.session.scalar(
            select(func.max(PersonalRecord.value)).where(
                PersonalRecord.user_id == user_id,
                PersonalRecord.exercise_id == exercise_id,
                PersonalRecord.record_type == record_type,
            )
        )

    async def count_records(self, workout_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(PersonalRecord)
            .where(PersonalRecord.workout_id == workout_id)
        )
        return int(value or 0)
