"""The mobile journal's replay contract against real PostgreSQL transactions."""

import os
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from test_account_security_database import login, seed_account

from nxtrep_backend.db.models import Exercise, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL required"
)


@pytest.mark.asyncio
async def test_four_record_types_replay_once_and_workout_exposes_client_id():
    user_id, username, password = await seed_account()
    now = datetime.now(UTC).isoformat()
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api/v1"
        ) as client:
            pair = await login(client, username, password, "Offline contract test")
            client.headers["Authorization"] = f"Bearer {pair['access_token']}"

            async def twice(path, body):
                key = str(uuid4())
                first = await client.post(path, json=body, headers={"Idempotency-Key": key})
                assert first.status_code == 201
                replay = await client.post(path, json=body, headers={"Idempotency-Key": key})
                assert replay.status_code == 201
                assert replay.json() == first.json()
                return first.json()

            water = await twice("/nutrition/water", {"amount_ml": 321, "consumed_at": now})
            measurement = await twice(
                "/body/measurements",
                {
                    "measured_at": now,
                    "weight_kg": "71.2",
                    "source": "manual",
                },
            )
            meal = await twice(
                "/nutrition/entries",
                {
                    "meal_type": "lunch",
                    "eaten_at": now,
                    "items": [
                        {
                            "name": "离线验收米饭",
                            "amount_g": "100",
                            "basis_amount_g": "100",
                            "kcal": "130",
                            "protein_g": "2",
                            "carbs_g": "28",
                            "fat_g": "0.3",
                            "source": "user",
                            "confidence": "confirmed",
                        }
                    ],
                },
            )
            workout = await twice("/workouts", {"started_at": now})
            async with SessionFactory() as session:
                exercise_id = await session.scalar(
                    select(Exercise.id).where(Exercise.owner_user_id.is_(None)).limit(1)
                )
            assert exercise_id is not None
            added = await client.post(
                f"/workouts/{workout['id']}/exercises",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "exercise_id": str(exercise_id),
                    "target_sets": 3,
                    "rep_min": 8,
                    "rep_max": 12,
                    "expected_workout_version": workout["version"],
                },
            )
            assert added.status_code == 201
            set_id = str(uuid4())
            completed = await twice(
                f"/workouts/{workout['id']}/sets",
                {
                    "client_generated_id": set_id,
                    "workout_exercise_id": added.json()["exercises"][0]["id"],
                    "set_index": 1,
                    "weight_kg": "20",
                    "reps": 8,
                    "completed_at": now,
                },
            )
            assert completed["client_generated_id"] == set_id
            active = (await client.get("/workouts/active")).json()
            assert len(active["exercises"][0]["sets"]) == 1
            assert active["exercises"][0]["sets"][0]["client_generated_id"] == set_id
            measured = (await client.get("/body/measurements")).json()["list"]
            assert [item["id"] for item in measured] == [measurement["id"]]
            entries = (await client.get("/nutrition/entries", params={"date": day})).json()
            assert [item["id"] for item in entries] == [meal["id"]]
            waters = (await client.get("/nutrition/water", params={"date": day})).json()
            assert [item["id"] for item in waters] == [water["id"]]
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
