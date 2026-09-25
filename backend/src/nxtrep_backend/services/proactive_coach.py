"""Opt-in, repeatable coaching observations over recorded user facts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    AppNotification,
    CalendarEvent,
    NotificationSetting,
    NutritionEntry,
    Workout,
)

CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
COACH_NAMESPACE = UUID("81359e64-5b92-4dba-9c87-36ec97b25aa0")
COACH_CATEGORY = "proactive_coach"


@dataclass(frozen=True, slots=True)
class CoachObservation:
    kind: str
    subject_id: str
    title: str
    body: str
    route: str


class ProactiveCoachService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def review_user(self, user_id: UUID, today: date | None = None) -> list[AppNotification]:
        """Create at most one notification per fact and day, only after explicit opt-in."""
        settings = await self.session.get(NotificationSetting, user_id)
        if (
            settings is None
            or not settings.enabled
            or settings.categories.get(COACH_CATEGORY) is not True
        ):
            return []

        today = today or datetime.now(CHINA_TIMEZONE).date()
        yesterday = today - timedelta(days=1)
        start = datetime.combine(yesterday, time.min, tzinfo=CHINA_TIMEZONE)
        end = datetime.combine(today, time.min, tzinfo=CHINA_TIMEZONE)
        observations: list[CoachObservation] = []

        missed_events = list(
            await self.session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.scheduled_date == yesterday,
                    CalendarEvent.status.in_(["planned", "missed"]),
                    CalendarEvent.actual_workout_id.is_(None),
                )
                .order_by(CalendarEvent.created_at)
            )
        )
        if missed_events:
            observations.append(
                CoachObservation(
                    kind="missed_workout",
                    subject_id=str(missed_events[0].id),
                    title="昨天日历中的训练尚未标记完成",
                    body="如果已经训练，请核对记录；否则可以查看日历并调整安排。",
                    route="plan",
                )
            )

        high_fatigue = await self.session.scalar(
            select(Workout)
            .where(
                Workout.user_id == user_id,
                Workout.status == "completed",
                Workout.ended_at >= start,
                Workout.ended_at < end,
                Workout.fatigue >= 4,
            )
            .order_by(Workout.ended_at.desc())
            .limit(1)
        )
        if high_fatigue is not None:
            observations.append(
                CoachObservation(
                    kind="recovery_check",
                    subject_id=str(high_fatigue.id),
                    title="昨天记录了较高的训练后疲劳",
                    body="今天可以先查看恢复状态，再决定是否按原计划训练；这不是医学判断。",
                    route="agent",
                )
            )

        if settings.frequency != "important_only":
            yesterday_records = await self.session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(
                    NutritionEntry.user_id == user_id,
                    NutritionEntry.deleted_at.is_(None),
                    NutritionEntry.eaten_at >= start,
                    NutritionEntry.eaten_at < end,
                )
            )
            habit_start = start - timedelta(days=7)
            recent_records = await self.session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(
                    NutritionEntry.user_id == user_id,
                    NutritionEntry.deleted_at.is_(None),
                    NutritionEntry.eaten_at >= habit_start,
                    NutritionEntry.eaten_at < start,
                )
            )
            if not yesterday_records and recent_records:
                observations.append(
                    CoachObservation(
                        kind="nutrition_log_gap",
                        subject_id=yesterday.isoformat(),
                        title="昨天没有饮食记录",
                        body="如果昨天有进食且你正在追踪营养，可以补记；没有记录不代表没有进食。",
                        route="nutrition",
                    )
                )

        ids: list[UUID] = []
        for item in observations:
            notification_id = uuid5(
                COACH_NAMESPACE, f"{user_id}:{today}:{item.kind}:{item.subject_id}"
            )
            ids.append(notification_id)
            await self.session.execute(
                insert(AppNotification)
                .values(
                    id=notification_id,
                    user_id=user_id,
                    category=COACH_CATEGORY,
                    title=item.title,
                    body=item.body,
                    data={
                        "kind": item.kind,
                        "subject_id": item.subject_id,
                        "review_date": today.isoformat(),
                        "route": item.route,
                    },
                )
                .on_conflict_do_nothing(index_elements=[AppNotification.id])
            )
        if not ids:
            return []
        return list(
            await self.session.scalars(
                select(AppNotification)
                .where(AppNotification.id.in_(ids))
                .order_by(AppNotification.created_at.desc())
            )
        )
