from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    BodyFatEstimate,
    BodyMeasurement,
    BodyMeasurementRevision,
    CalendarEvent,
    ExerciseMuscle,
    NutritionEntry,
    PersonalRecord,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)


class SqlAlchemyBodyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_measurement(self, item: BodyMeasurement) -> BodyMeasurement:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_measurement(
        self, user_id: UUID, measurement_id: UUID, *, lock: bool = False
    ) -> BodyMeasurement | None:
        statement = select(BodyMeasurement).where(
            BodyMeasurement.id == measurement_id,
            BodyMeasurement.user_id == user_id,
            BodyMeasurement.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_measurements(
        self,
        user_id: UUID,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> tuple[list[BodyMeasurement], int]:
        conditions = [
            BodyMeasurement.user_id == user_id,
            BodyMeasurement.deleted_at.is_(None),
        ]
        if start_date:
            conditions.append(func.date(BodyMeasurement.measured_at) >= start_date)
        if end_date:
            conditions.append(func.date(BodyMeasurement.measured_at) <= end_date)
        total = await self.session.scalar(
            select(func.count()).select_from(BodyMeasurement).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(BodyMeasurement)
                .where(*conditions)
                .order_by(BodyMeasurement.measured_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def measurements_in_range(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> list[BodyMeasurement]:
        items, _ = await self.list_measurements(user_id, start_date, end_date, 1, 10_000)
        return list(reversed(items))

    async def add_revision(self, revision: BodyMeasurementRevision) -> None:
        self.session.add(revision)
        await self.session.flush()

    async def add_body_fat(self, estimate: BodyFatEstimate) -> None:
        self.session.add(estimate)
        await self.session.flush()

    async def list_body_fat(
        self,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[BodyFatEstimate], int]:
        condition = BodyFatEstimate.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(BodyFatEstimate).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(BodyFatEstimate)
                .where(condition)
                .order_by(BodyFatEstimate.calculated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def body_fat_in_range(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> list[BodyFatEstimate]:
        return list(
            await self.session.scalars(
                select(BodyFatEstimate)
                .where(
                    BodyFatEstimate.user_id == user_id,
                    func.date(BodyFatEstimate.calculated_at) >= start_date,
                    func.date(BodyFatEstimate.calculated_at) <= end_date,
                )
                .order_by(BodyFatEstimate.calculated_at)
            )
        )

    async def progress_rows(self, user_id: UUID, start_date: date, end_date: date):
        workouts = list(
            await self.session.scalars(
                select(Workout).where(
                    Workout.user_id == user_id,
                    func.date(Workout.started_at) >= start_date,
                    func.date(Workout.started_at) <= end_date,
                )
            )
        )
        entries = list(
            await self.session.scalars(
                select(NutritionEntry).where(
                    NutritionEntry.user_id == user_id,
                    NutritionEntry.deleted_at.is_(None),
                    func.date(NutritionEntry.eaten_at) >= start_date,
                    func.date(NutritionEntry.eaten_at) <= end_date,
                )
            )
        )
        measurements = await self.measurements_in_range(user_id, start_date, end_date)
        records = list(
            await self.session.scalars(
                select(PersonalRecord).where(
                    PersonalRecord.user_id == user_id,
                    func.date(PersonalRecord.occurred_at) >= start_date,
                    func.date(PersonalRecord.occurred_at) <= end_date,
                )
            )
        )
        calendar_events = list(
            await self.session.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.scheduled_date >= start_date,
                    CalendarEvent.scheduled_date <= end_date,
                )
            )
        )
        return workouts, entries, measurements, records, calendar_events

    async def list_records(
        self,
        user_id: UUID,
        exercise_id: UUID | None,
        record_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[PersonalRecord], int]:
        conditions = [PersonalRecord.user_id == user_id]
        if exercise_id:
            conditions.append(PersonalRecord.exercise_id == exercise_id)
        if record_type:
            conditions.append(PersonalRecord.record_type == record_type)
        total = await self.session.scalar(
            select(func.count()).select_from(PersonalRecord).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(PersonalRecord)
                .where(*conditions)
                .order_by(PersonalRecord.occurred_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_record(self, user_id: UUID, record_id: UUID) -> PersonalRecord | None:
        return await self.session.scalar(
            select(PersonalRecord).where(
                PersonalRecord.id == record_id,
                PersonalRecord.user_id == user_id,
            )
        )

    async def muscle_volume_rows(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> list[tuple[str, str, object, int]]:
        return list(
            (
                await self.session.execute(
                    select(
                        ExerciseMuscle.muscle_code,
                        ExerciseMuscle.role,
                        WorkoutSet.weight_kg,
                        WorkoutSet.reps,
                    )
                    .join(
                        WorkoutExercise,
                        WorkoutExercise.exercise_id == ExerciseMuscle.exercise_id,
                    )
                    .join(Workout, Workout.id == WorkoutExercise.workout_id)
                    .join(
                        WorkoutSet,
                        WorkoutSet.workout_exercise_id == WorkoutExercise.id,
                    )
                    .where(
                        Workout.user_id == user_id,
                        Workout.status == "completed",
                        WorkoutSet.voided_at.is_(None),
                        func.date(Workout.started_at) >= start_date,
                        func.date(Workout.started_at) <= end_date,
                    )
                )
            ).all()
        )
