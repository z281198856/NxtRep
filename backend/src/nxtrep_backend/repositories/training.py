from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import (
    CalendarEvent,
    CalendarRescheduleDraft,
    Exercise,
    TrainingPlanDraft,
    TrainingPlanVersion,
    TrainingTemplate,
)


class SqlAlchemyTrainingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_templates(
        self,
        *,
        goal_type: str | None,
        days_per_week: int | None,
        equipment: str | None,
    ) -> list[TrainingTemplate]:
        conditions = [TrainingTemplate.is_active.is_(True)]
        if goal_type:
            conditions.append(TrainingTemplate.goal_types.contains([goal_type]))
        if days_per_week:
            conditions.append(TrainingTemplate.days_per_week == days_per_week)
        if equipment:
            conditions.append(TrainingTemplate.equipment.contains([equipment]))
            # A single-equipment request must not select a mixed-equipment plan.
            # Unloaded accessory movements remain available in all tracks.
            conditions.append(
                TrainingTemplate.equipment.contained_by(list({equipment, "bodyweight"}))
            )
        result = await self.session.scalars(
            select(TrainingTemplate).where(*conditions).order_by(TrainingTemplate.name)
        )
        return list(result)

    async def get_template(self, template_id: UUID) -> TrainingTemplate | None:
        return await self.session.scalar(
            select(TrainingTemplate).where(
                TrainingTemplate.id == template_id, TrainingTemplate.is_active.is_(True)
            )
        )

    async def template_exercise_names(self, exercise_ids: set[UUID]) -> dict[str, str]:
        if not exercise_ids:
            return {}
        rows = await self.session.execute(
            select(Exercise.id, Exercise.name_zh).where(
                Exercise.id.in_(exercise_ids),
                Exercise.deleted_at.is_(None),
                Exercise.owner_user_id.is_(None),
            )
        )
        return {str(exercise_id): name for exercise_id, name in rows}

    async def delete_draft(self, draft: TrainingPlanDraft) -> None:
        await self.session.delete(draft)
        await self.session.flush()

    async def visible_exercise_ids(self, user_id: UUID, exercise_ids: set[UUID]) -> set[UUID]:
        if not exercise_ids:
            return set()
        return set(
            await self.session.scalars(
                select(Exercise.id).where(
                    Exercise.id.in_(exercise_ids),
                    Exercise.deleted_at.is_(None),
                    (Exercise.owner_user_id.is_(None) | (Exercise.owner_user_id == user_id)),
                )
            )
        )

    async def get_visible_exercise(self, user_id: UUID, exercise_id: UUID) -> Exercise | None:
        return await self.session.scalar(
            select(Exercise).where(
                Exercise.id == exercise_id,
                Exercise.deleted_at.is_(None),
                (Exercise.owner_user_id.is_(None) | (Exercise.owner_user_id == user_id)),
            )
        )

    async def add_draft(self, draft: TrainingPlanDraft) -> TrainingPlanDraft:
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def get_draft(
        self, user_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> TrainingPlanDraft | None:
        statement = select(TrainingPlanDraft).where(
            TrainingPlanDraft.id == draft_id, TrainingPlanDraft.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_active_plan(self, user_id: UUID) -> TrainingPlanVersion | None:
        return await self.session.scalar(
            select(TrainingPlanVersion).where(
                TrainingPlanVersion.user_id == user_id, TrainingPlanVersion.status == "active"
            )
        )

    async def get_plan_version(self, version_id: UUID) -> TrainingPlanVersion | None:
        return await self.session.get(TrainingPlanVersion, version_id)

    async def get_plan_version_for_user(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
        version: int,
        lock: bool = False,
    ) -> TrainingPlanVersion | None:
        statement = select(TrainingPlanVersion).where(
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.plan_id == plan_id,
            TrainingPlanVersion.version == version,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_latest_plan(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
    ) -> TrainingPlanVersion | None:
        return await self.session.scalar(
            select(TrainingPlanVersion)
            .where(
                TrainingPlanVersion.user_id == user_id,
                TrainingPlanVersion.plan_id == plan_id,
            )
            .order_by(TrainingPlanVersion.version.desc())
            .limit(1)
        )

    async def list_latest_plans(
        self,
        *,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[TrainingPlanVersion], int]:
        versions = list(
            await self.session.scalars(
                select(TrainingPlanVersion)
                .where(TrainingPlanVersion.user_id == user_id)
                .order_by(
                    TrainingPlanVersion.plan_id,
                    TrainingPlanVersion.version.desc(),
                )
            )
        )
        latest_by_plan: dict[UUID, TrainingPlanVersion] = {}
        for item in versions:
            latest_by_plan.setdefault(item.plan_id, item)
        latest = sorted(
            latest_by_plan.values(),
            key=lambda item: item.activated_at,
            reverse=True,
        )
        offset = (page - 1) * page_size
        return latest[offset : offset + page_size], len(latest)

    async def list_plan_versions(
        self, user_id: UUID, plan_id: UUID, page: int, page_size: int
    ) -> tuple[list[TrainingPlanVersion], int]:
        conditions = [
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.plan_id == plan_id,
        ]
        total = await self.session.scalar(
            select(func.count()).select_from(TrainingPlanVersion).where(*conditions)
        )
        versions = list(
            await self.session.scalars(
                select(TrainingPlanVersion)
                .where(*conditions)
                .order_by(TrainingPlanVersion.version.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return versions, int(total or 0)

    async def add_plan_version(self, version: TrainingPlanVersion) -> TrainingPlanVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def list_calendar(
        self, user_id: UUID, start_date: date, end_date: date
    ) -> list[CalendarEvent]:
        await self.session.execute(
            update(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.scheduled_date < datetime.now(CHINA_TIMEZONE).date(),
                CalendarEvent.status == "planned",
                CalendarEvent.actual_workout_id.is_(None),
            )
            .values(status="missed")
        )
        await self.session.flush()
        return list(
            await self.session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.scheduled_date >= start_date,
                    CalendarEvent.scheduled_date <= end_date,
                )
                .order_by(CalendarEvent.scheduled_date, CalendarEvent.created_at)
            )
        )

    async def get_calendar_event(
        self, user_id: UUID, event_id: UUID, *, lock: bool = False
    ) -> CalendarEvent | None:
        statement = select(CalendarEvent).where(
            CalendarEvent.id == event_id, CalendarEvent.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_event_on_date(self, user_id: UUID, target_date: date) -> CalendarEvent | None:
        return await self.session.scalar(
            select(CalendarEvent).where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.scheduled_date == target_date,
                CalendarEvent.status == "planned",
            )
        )

    async def add_reschedule_draft(self, draft: CalendarRescheduleDraft) -> CalendarRescheduleDraft:
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def get_reschedule_draft(
        self, user_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> CalendarRescheduleDraft | None:
        statement = select(CalendarRescheduleDraft).where(
            CalendarRescheduleDraft.id == draft_id,
            CalendarRescheduleDraft.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def add_calendar_events(self, events: list[CalendarEvent]) -> None:
        self.session.add_all(events)
        await self.session.flush()

    async def add_calendar_event(self, event: CalendarEvent) -> CalendarEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def delete_future_planned_events(self, user_id: UUID, from_date: date) -> None:
        await self.session.execute(
            delete(CalendarEvent).where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.scheduled_date >= from_date,
                CalendarEvent.status == "planned",
                CalendarEvent.actual_workout_id.is_(None),
            )
        )
        await self.session.flush()

    async def list_future_plan_events(
        self, user_id: UUID, plan_version_id: UUID, from_date: date
    ) -> list[CalendarEvent]:
        return list(
            await self.session.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.plan_version_id == plan_version_id,
                    CalendarEvent.scheduled_date >= from_date,
                    CalendarEvent.status == "planned",
                    CalendarEvent.actual_workout_id.is_(None),
                )
            )
        )
