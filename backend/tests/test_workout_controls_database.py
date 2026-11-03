import os
from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.db.models import CalendarEvent, Exercise, User, Workout, WorkoutSet
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
@pytest.mark.parametrize("planned", [False, True])
async def test_real_api_workout_targets_timer_idempotency_and_delete_then_add(planned):
    async with SessionFactory() as session:
        try:
            user = User(username=f"workout-controls-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            exercise = Exercise(owner_user_id=user.id, name_zh="验收卧推", equipment="barbell")
            session.add(exercise)
            await session.flush()
            event = None
            original_snapshot = {
                "exercises": [
                    {
                        "exercise_id": str(exercise.id),
                        "target_sets": 4,
                        "rep_min": 8,
                        "rep_max": 12,
                        "rest_seconds": 90,
                        "order_no": 1,
                    }
                ]
            }
            if planned:
                event = CalendarEvent(
                    user_id=user.id,
                    scheduled_date=date.today(),
                    title="验收训练",
                    estimated_minutes=45,
                    status="planned",
                    plan_day_id=uuid4(),
                    content_snapshot=deepcopy(original_snapshot),
                )
                session.add(event)
                await session.flush()

            async def db_override():
                yield session

            app.dependency_overrides[get_db_session] = db_override
            app.dependency_overrides[get_current_user] = lambda: user
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
            ) as client:
                result = await client.post(
                    "/workouts",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={
                        "started_at": datetime.now(UTC).isoformat(),
                        "calendar_event_id": str(event.id) if event else None,
                    },
                )
                assert result.status_code == 201, result.text
                workout = result.json()
                assert bool(workout["calendar_event_id"]) is planned
                if not planned:
                    result = await client.post(
                        f"/workouts/{workout['id']}/exercises",
                        headers={"Idempotency-Key": str(uuid4())},
                        json={
                            "exercise_id": str(exercise.id),
                            "target_sets": 4,
                            "rest_seconds": 90,
                            "expected_workout_version": workout["version"],
                        },
                    )
                    assert result.status_code == 201, result.text
                    workout = result.json()
                item_id = workout["exercises"][0]["id"]
                target_url = f"/workouts/{workout['id']}/exercises/{item_id}/target"
                change = {
                    "target_sets": 6,
                    "rest_seconds": 75,
                    "expected_workout_version": workout["version"],
                }
                response = await client.patch(target_url, json=change)
                assert response.status_code == 200, response.text
                assert response.json()["exercises"][0]["target_snapshot"]["sets"] == 6
                assert (await client.patch(target_url, json=change)).status_code == 409
                restored = (await client.get("/workouts/active")).json()
                assert restored["exercises"][0]["target_snapshot"]["rest_seconds"] == 75
                set_body = {
                    "client_generated_id": str(uuid4()),
                    "workout_exercise_id": item_id,
                    "set_index": 1,
                    "weight_kg": 55,
                    "reps": 8,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
                key = {"Idempotency-Key": str(uuid4())}
                set_url = f"/workouts/{workout['id']}/sets"
                first = await client.post(set_url, headers=key, json=set_body)
                repeated = await client.post(set_url, headers=key, json=set_body)
                assert first.status_code == repeated.status_code == 201
                assert first.json()["id"] == repeated.json()["id"]
                restored = (await client.get("/workouts/active")).json()
                assert len(restored["exercises"][0]["sets"]) == 1
                assert restored["rest_timer"]["duration_seconds"] == 75
                assert 70 <= restored["rest_timer"]["remaining_seconds"] <= 75
                invalid = await client.patch(
                    target_url,
                    json={"target_sets": 0, "expected_workout_version": restored["version"]},
                )
                assert invalid.status_code == 422

                removed = await client.request(
                    "DELETE",
                    f"{set_url}/{first.json()['id']}",
                    json={"reason": "验收删除再添加", "expected_version": first.json()["version"]},
                )
                assert removed.status_code == 200, removed.text
                set_body["client_generated_id"] = str(uuid4())
                added = await client.post(
                    set_url, headers={"Idempotency-Key": str(uuid4())}, json=set_body
                )
                assert added.status_code == 201, added.text
                assert added.json()["set_index"] == 2
                active = (await client.get("/workouts/active")).json()
                assert len(active["exercises"][0]["sets"]) == 1
                assert event is None or event.content_snapshot == original_snapshot

                # Another user's resource remains unreachable through the target route.
                other = User(username=f"workout-other-{uuid4().hex}", password_setup_required=False)
                session.add(other)
                await session.flush()
                app.dependency_overrides[get_current_user] = lambda: other
                forbidden = await client.patch(
                    target_url,
                    json={"target_sets": 7, "expected_workout_version": active["version"]},
                )
                assert forbidden.status_code == 404
                assert (
                    await session.scalar(select(Workout).where(Workout.user_id == other.id)) is None
                )
                assert (
                    len(
                        list(
                            await session.scalars(
                                select(WorkoutSet).where(
                                    WorkoutSet.workout_id == workout["id"],
                                    WorkoutSet.voided_at.is_(None),
                                )
                            )
                        )
                    )
                    == 1
                )
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            app.dependency_overrides.pop(get_current_user, None)
            await session.rollback()
