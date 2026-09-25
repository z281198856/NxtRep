import os
from datetime import datetime, time, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.db.models import (
    AppNotification,
    AuditEvent,
    CalendarEvent,
    NotificationSetting,
    NutritionEntry,
    User,
    Workout,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app
from nxtrep_backend.services.proactive_coach import CHINA_TIMEZONE

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Requires PostgreSQL"),
]


async def test_opt_in_review_is_actionable_idempotent_and_does_not_change_facts():
    today = datetime.now(CHINA_TIMEZONE).date()
    yesterday = today - timedelta(days=1)
    start = datetime.combine(yesterday, time(9), tzinfo=CHINA_TIMEZONE)
    async with SessionFactory() as session:
        transaction = await session.begin()
        previous_overrides = app.dependency_overrides.copy()
        try:
            user = User(username=f"coach-review-{uuid4().hex}", password_setup_required=False)
            other_user = User(username=f"coach-other-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            session.add(other_user)
            await session.flush()
            other_notice = AppNotification(
                user_id=other_user.id,
                category="proactive_coach",
                title="private",
                body="private",
                data={"kind": "missed_workout"},
            )
            session.add(other_notice)
            session.add_all(
                [
                    CalendarEvent(
                        user_id=user.id,
                        scheduled_date=yesterday,
                        status="planned",
                        title="哑铃训练",
                        estimated_minutes=40,
                    ),
                    Workout(
                        user_id=user.id,
                        status="completed",
                        started_at=start,
                        ended_at=start + timedelta(minutes=35),
                        fatigue=4,
                    ),
                    NutritionEntry(
                        user_id=user.id,
                        meal_type="lunch",
                        eaten_at=start - timedelta(days=2),
                        items=[],
                        totals={},
                    ),
                ]
            )
            await session.flush()
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_db_session] = lambda: session
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                disabled = await client.post("/api/v1/agent/proactive/review")
                assert disabled.status_code == 200, disabled.text
                assert disabled.json() == []

                settings = await client.get("/api/v1/notification-settings")
                assert settings.status_code == 200
                assert settings.json()["enabled"] is False
                without_category = await client.patch(
                    "/api/v1/notification-settings",
                    json={
                        "enabled": True,
                        "categories": {"proactive_coach": False},
                        "frequency": "daily",
                        "expected_version": settings.json()["version"],
                    },
                )
                assert without_category.status_code == 200, without_category.text
                assert (await client.post("/api/v1/agent/proactive/review")).json() == []

                enabled = await client.patch(
                    "/api/v1/notification-settings",
                    json={
                        "enabled": True,
                        "categories": {"proactive_coach": True},
                        "frequency": "daily",
                        "expected_version": without_category.json()["version"],
                    },
                )
                assert enabled.status_code == 200, enabled.text
                opted_in = await session.scalar(
                    select(NotificationSetting.user_id).where(
                        NotificationSetting.user_id == user.id,
                        NotificationSetting.enabled.is_(True),
                        NotificationSetting.categories["proactive_coach"].as_boolean().is_(True),
                    )
                )
                assert opted_in == user.id

                first = await client.post("/api/v1/agent/proactive/review")
                assert first.status_code == 200, first.text
                assert {row["data"]["kind"] for row in first.json()} == {
                    "missed_workout",
                    "recovery_check",
                    "nutrition_log_gap",
                }
                assert all(row["category"] == "proactive_coach" for row in first.json())
                second = await client.post("/api/v1/agent/proactive/review")
                assert second.status_code == 200, second.text
                assert {row["id"] for row in second.json()} == {row["id"] for row in first.json()}
                count = await session.scalar(
                    select(func.count())
                    .select_from(AppNotification)
                    .where(AppNotification.user_id == user.id)
                )
                assert count == 3

                inbox = await client.get(
                    "/api/v1/notifications",
                    params={"unread_only": "true", "category": "proactive_coach"},
                )
                assert inbox.status_code == 200
                assert inbox.json()["total"] == 3
                notice_id = first.json()[0]["id"]
                feedback_path = f"/api/v1/agent/proactive/notices/{notice_id}/feedback"
                invalid = await client.put(feedback_path, json={"rating": "unsafe"})
                assert invalid.status_code == 422
                foreign = await client.put(
                    f"/api/v1/agent/proactive/notices/{other_notice.id}/feedback",
                    json={"rating": "helpful"},
                )
                assert foreign.status_code == 404
                feedback = await client.put(feedback_path, json={"rating": "inaccurate"})
                assert feedback.status_code == 200, feedback.text
                assert feedback.json()["data"]["feedback"] == {"rating": "inaccurate"}
                repeated = await client.put(feedback_path, json={"rating": "inaccurate"})
                assert repeated.status_code == 200
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.user_id == user.id,
                            AuditEvent.action == "proactive_feedback.recorded",
                        )
                    )
                    == 1
                )
                read = await client.post(f"/api/v1/notifications/{first.json()[0]['id']}/read")
                assert read.status_code == 200
                assert read.json()["read_at"] is not None
                after_read = await client.get(
                    "/api/v1/notifications",
                    params={"unread_only": "true", "category": "proactive_coach"},
                )
                assert after_read.json()["total"] == 2
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(CalendarEvent)
                        .where(
                            CalendarEvent.user_id == user.id,
                            CalendarEvent.status == "planned",
                        )
                    )
                    == 1
                )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            await transaction.rollback()
