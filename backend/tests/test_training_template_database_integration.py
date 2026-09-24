import os
from datetime import date, timedelta
from itertools import product
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_training_template_catalog import load_catalog

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.db.models import Exercise, TrainingTemplate, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_DATABASE_TESTS") != "1", reason="Requires migrated PostgreSQL"
    ),
]


@pytest.mark.parametrize("equipment", ["bodyweight", "dumbbell", "barbell", "cable"])
async def test_generate_validate_and_activate_equipment_plans_via_api(equipment):
    async with SessionFactory() as session:
        transaction = await session.begin()
        previous_overrides = app.dependency_overrides.copy()
        try:
            user = User(username=f"template-qa-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_db_session] = lambda: session
            exercises = {str(item.id): item for item in (await session.scalars(select(Exercise)))}
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                goals = ("muscle_gain", "fat_loss_retain", "recomposition", "maintain", "strength")
                for goal, frequency in product(goals, range(1, 8)):
                    response = await client.post(
                        "/api/v1/training/plan-drafts:generate",
                        headers={"Idempotency-Key": str(uuid4())},
                        json={
                            "goal_type": goal,
                            "days_per_week": frequency,
                            "equipment": equipment,
                        },
                    )
                    assert response.status_code == 201, response.text
                    draft = response.json()
                    assert draft["weekly_frequency"] == frequency
                    assert len(draft["days"]) == frequency
                    assert not draft["validation_errors"]
                    for day in draft["days"]:
                        assert day["exercises"]
                        for item in day["exercises"]:
                            exercise = exercises[item["exercise_id"]]
                            assert exercise.equipment in {equipment, "bodyweight"}
                            assert exercise.deleted_at is None
                            assert exercise.owner_user_id is None
                            if equipment == "bodyweight":
                                assert exercise.name_zh != "引体向上"
                    validation = await client.post(
                        f"/api/v1/training/plan-drafts/{draft['id']}/validate",
                        json={"expected_version": draft["version"]},
                    )
                    assert validation.status_code == 200, validation.text
                    assert validation.json()["valid"] is True

                # Activate the last, seven-session draft and check four weeks of snapshots.
                submit = await client.post(
                    f"/api/v1/training/plan-drafts/{draft['id']}/submit",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"expected_version": draft["version"]},
                )
                assert submit.status_code == 200, submit.text
                confirmation_id = submit.json()["confirmation_id"]
                detail = await client.get(f"/api/v1/confirmations/{confirmation_id}")
                approval = await client.post(
                    f"/api/v1/confirmations/{confirmation_id}/approve",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"expected_version": detail.json()["version"]},
                )
                assert approval.status_code == 200, approval.text
                assert approval.json()["status"] == "succeeded"
                calendar = await client.get(
                    "/api/v1/calendar",
                    params={
                        "start_date": str(date.today()),
                        "end_date": str(date.today() + timedelta(days=27)),
                    },
                )
                assert calendar.status_code == 200, calendar.text
                assert len(calendar.json()) == 28
                assert sum("轻量恢复" in event["title"] for event in calendar.json()) == 12
                listed = await client.get(
                    "/api/v1/training/templates", params={"equipment": equipment}
                )
                assert listed.status_code == 200, listed.text
                assert listed.json()
                assert all(
                    set(row["equipment"]) <= {equipment, "bodyweight"} for row in listed.json()
                )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            await transaction.rollback()


async def test_catalog_can_be_downgraded_and_reapplied_without_deleting_exercises():
    catalog = load_catalog()
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            connection = await session.connection()

            def replay(sync_connection):
                catalog.op = Operations(MigrationContext.configure(sync_connection))
                catalog.downgrade()
                catalog.upgrade()

            await connection.run_sync(replay)
            ids = [row["id"] for row in catalog.template_rows()]
            seeded = list(
                await session.scalars(select(TrainingTemplate).where(TrainingTemplate.id.in_(ids)))
            )
            assert len(seeded) == len(ids)
            for slug, *_ in catalog.NEW_EXERCISES:
                assert await session.get(Exercise, UUID(str(catalog.exercise_id(slug)))) is not None
        finally:
            await transaction.rollback()
