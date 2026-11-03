import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.agents.tools.nutrition import build_nutrition_read_tools
from nxtrep_backend.agents.tools.training import build_training_draft_tools
from nxtrep_backend.db.models import (
    AppNotification,
    CalendarEvent,
    NotificationSetting,
    NutritionEntry,
    NutritionTargetVersion,
    User,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.platform import SqlAlchemyPlatformRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.coaching_review import build_progress_review
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.platform import PlatformService
from nxtrep_backend.services.proactive_coach import (
    CHINA_TIMEZONE,
    ProactiveCoachService,
    ProactiveNoticeNotFoundError,
)
from nxtrep_backend.services.training import TrainingService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL"),
]


@pytest.mark.parametrize("has_target", [False, True])
async def test_meal_option_uses_real_target_reports_excess_and_saves_nothing(has_target):
    async with SessionFactory() as session:
        try:
            user = User(username=f"meal-preview-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            today = datetime.now(CHINA_TIMEZONE).date()
            if has_target:
                session.add(
                    NutritionTargetVersion(
                        user_id=user.id,
                        effective_from=today,
                        version=1,
                        status="active",
                        values={
                            "kcal_min": "100",
                            "kcal_max": "200",
                            "protein_min_g": "10",
                            "protein_max_g": "20",
                            "carbs_min_g": "10",
                            "carbs_max_g": "20",
                            "fat_min_g": "5",
                            "fat_max_g": "10",
                        },
                    )
                )
                await session.flush()
            nutrition = NutritionService(
                SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
            )
            goals = SimpleNamespace(
                get_goals_and_constraints=AsyncMock(
                    return_value=SimpleNamespace(
                        constraints=SimpleNamespace(
                            allergies=["花生"], dietary_preferences=["素食"]
                        )
                    )
                )
            )
            tool = next(
                t
                for t in build_nutrition_read_tools(
                    SimpleNamespace(
                        user_id=user.id, nutrition_service=nutrition, goals_service=goals
                    )
                )
                if t.name == "calculate_meal_option"
            )
            result = await tool.ainvoke(
                {
                    "day": today.isoformat(),
                    "items": [
                        {
                            "name": "花生测试",
                            "amount_g": "200",
                            "basis_amount_g": "100",
                            "kcal": "300",
                            "protein_g": "20",
                            "carbs_g": "25",
                            "fat_g": "15",
                            "nutrient_basis": "total_consumed",
                            "source": "model_estimated",
                            "confidence": "low",
                        }
                    ],
                }
            )
            assert Decimal(result["meal_totals"]["kcal"]) == Decimal("300")
            assert result["saved"] is False
            assert result["suitable"] is False and result["allergen_name_conflicts"] == ["花生"]
            if has_target:
                assert Decimal(result["remaining_after_meal"]["kcal_max"]) == -100
            else:
                assert result["remaining_after_meal"] is None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 0
            )
        finally:
            await session.rollback()


async def test_recovery_compression_changes_only_selected_event_after_confirmation():
    async with SessionFactory() as session:
        try:
            user = User(username=f"recovery-draft-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            repository = SqlAlchemyConfirmationRepository(session)
            training = TrainingService(SqlAlchemyTrainingRepository(session), repository)
            plan = await training.create_from_template(
                user.id, UUID("20000000-0000-4000-8000-000000000001"), None
            )
            card = await training.submit_draft(user.id, plan.id, plan.version)
            approval = DatabaseConfirmationService(repository)
            await approval.approve(user.id, card.id, card.version)
            events = list(
                await session.scalars(
                    select(CalendarEvent)
                    .where(CalendarEvent.user_id == user.id)
                    .order_by(CalendarEvent.scheduled_date)
                )
            )
            event = events[0]
            original = deepcopy(event.content_snapshot)
            other_versions = [
                (
                    item.id,
                    item.scheduled_date,
                    item.estimated_minutes,
                    deepcopy(item.content_snapshot),
                )
                for item in events[1:]
            ]
            tool = next(
                t
                for t in build_training_draft_tools(
                    SimpleNamespace(
                        user_id=user.id,
                        training_service=training,
                        body_service=BodyService(SqlAlchemyBodyRepository(session), repository),
                    )
                )
                if t.name == "propose_recovery_adjustment"
            )
            result = await tool.ainvoke(
                {"event_id": str(event.id), "target_minutes": 15, "reason": "今天只安排短训练"}
            )
            assert result["status"] == "confirmation_required"
            assert event.estimated_minutes > 15 and event.content_snapshot == original
            new = result["confirmation"]
            await approval.approve(user.id, UUID(new["confirmation_id"]), new["version"])
            await session.refresh(event)
            assert event.estimated_minutes == 15 and event.actual_workout_id is None
            assert [
                (
                    item.id,
                    item.scheduled_date,
                    item.estimated_minutes,
                    deepcopy(item.content_snapshot),
                )
                for item in events[1:]
            ] == other_versions
            assert event.content_snapshot["exercises"]
            review = await build_progress_review(
                BodyService(SqlAlchemyBodyRepository(session)),
                user.id,
                event.scheduled_date - timedelta(days=6),
                event.scheduled_date,
            )
            assert review["weight_points"] == []
            report = await PlatformService(SqlAlchemyPlatformRepository(session)).generate_report(
                user.id,
                "weekly",
                event.scheduled_date - timedelta(days=6),
                event.scheduled_date,
            )
            assert report.facts["samples"] == {"weight": 0, "waist": 0}
            assert report.facts["comparison"]["period"] == review["previous_period"]
        finally:
            await session.rollback()


async def test_reminder_snooze_pause_and_restart_deduplicate(monkeypatch):

    async with SessionFactory() as session:
        try:
            user = User(username=f"snooze-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            now = datetime.now(UTC)
            today = now.astimezone(CHINA_TIMEZONE).date()
            settings = NotificationSetting(
                user_id=user.id,
                enabled=True,
                categories={"proactive_coach": True},
                frequency="daily",
            )
            session.add_all(
                [
                    settings,
                    CalendarEvent(
                        user_id=user.id,
                        scheduled_date=today - timedelta(days=1),
                        status="planned",
                        title="测试训练",
                        estimated_minutes=40,
                    ),
                ]
            )
            await session.flush()
            notices = await ProactiveCoachService(session).review_user(user.id, today)
            assert len(notices) == 1
            # A fresh service represents a restarted worker: the same notification ID is retained.
            assert (await ProactiveCoachService(session).review_user(user.id, today))[
                0
            ].id == notices[0].id
            await ProactiveCoachService(session).snooze(
                user.id, notices[0].id, now + timedelta(hours=1)
            )
            platform = SqlAlchemyPlatformRepository(session)
            assert (await platform.list_notifications(user.id, True, 1, 20, "proactive_coach"))[
                1
            ] == 0
            notices[0].data = {
                **notices[0].data,
                "snoozed_until": (now - timedelta(seconds=1)).isoformat(),
            }
            await session.flush()
            assert (await platform.list_notifications(user.id, True, 1, 20, "proactive_coach"))[
                1
            ] == 1
            settings.quiet_hours = {
                "enabled": False,
                "pause_until": (now + timedelta(days=1)).isoformat(),
            }
            await session.flush()
            assert await ProactiveCoachService(session).review_user(user.id, today) == []
            assert (await platform.list_notifications(user.id, True, 1, 20, "proactive_coach"))[
                1
            ] == 0
            local = now.astimezone(CHINA_TIMEZONE)
            settings.quiet_hours = {
                "enabled": True,
                "start": (local - timedelta(hours=3)).strftime("%H:%M"),
                "end": (local + timedelta(hours=3)).strftime("%H:%M"),
                "timezone": "Asia/Shanghai",
            }
            await session.flush()
            assert (await platform.list_notifications(user.id, True, 1, 20, "proactive_coach"))[
                1
            ] == 0
            assert await ProactiveCoachService(session).review_user(user.id, today) == []
            settings.quiet_hours = None
            await session.flush()
            assert (await platform.list_notifications(user.id, True, 1, 20, "proactive_coach"))[
                1
            ] == 1
            with pytest.raises(ProactiveNoticeNotFoundError):
                await ProactiveCoachService(session).snooze(
                    uuid4(), notices[0].id, now + timedelta(hours=1)
                )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AppNotification)
                    .where(AppNotification.user_id == user.id)
                )
                == 1
            )
        finally:
            await session.rollback()
