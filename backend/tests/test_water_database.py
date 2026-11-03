"""Optional local PostgreSQL verification; synthetic records are rolled back."""

import os
from datetime import datetime
from uuid import uuid4

import httpx
import pytest

from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import SessionFactory, get_db_session
from nxtrep_backend.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1", reason="Set RUN_DATABASE_TESTS=1 for PostgreSQL tests"
)


@pytest.mark.asyncio
async def test_water_persistence_idempotency_day_boundary_and_account_isolation():
    async with SessionFactory() as session:
        transaction = await session.begin()
        owner = User(username=f"water-{uuid4().hex}", password_setup_required=False)
        other = User(username=f"water-other-{uuid4().hex}", password_setup_required=False)
        session.add_all([owner, other])
        await session.flush()
        current = owner

        async def db():
            yield session

        app.dependency_overrides[get_current_user] = lambda: current
        app.dependency_overrides[get_db_session] = db
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"Idempotency-Key": str(uuid4())}
                # 16:00 UTC belongs to the next day in China.
                payload = {"amount_ml": 250, "consumed_at": "2026-10-22T16:00:00Z"}
                first = await client.post("/api/v1/nutrition/water", json=payload, headers=headers)
                assert first.status_code == 201, first.text
                replay = await client.post("/api/v1/nutrition/water", json=payload, headers=headers)
                assert replay.json() == first.json()
                entry_id = first.json()["id"]
                second = await client.post(
                    "/api/v1/nutrition/water",
                    json={"amount_ml": 500, "consumed_at": "2026-10-23T15:59:59Z"},
                    headers={"Idempotency-Key": str(uuid4())},
                )
                assert second.status_code == 201
                rows = await client.get("/api/v1/nutrition/water?date=2026-10-23")
                assert len(rows.json()) == 2
                assert (await client.get("/api/v1/nutrition/water?date=2026-10-22")).json() == []
                assert (await client.get("/api/v1/nutrition/water?date=2026-10-24")).json() == []
                summary = (
                    await client.get("/api/v1/nutrition/daily-summary?date=2026-10-23")
                ).json()
                assert summary["water_ml"] == 750
                assert float(summary["consumed"]["kcal"]) == 0
                assert float(summary["record_completeness"]) == 0
                current = other
                assert (await client.get("/api/v1/nutrition/water?date=2026-10-23")).json() == []
                assert (
                    await client.delete(f"/api/v1/nutrition/water/{entry_id}")
                ).status_code == 404
                current = owner
                assert (
                    await client.delete(f"/api/v1/nutrition/water/{entry_id}")
                ).status_code == 204
                summary = (
                    await client.get("/api/v1/nutrition/daily-summary?date=2026-10-23")
                ).json()
                assert summary["water_ml"] == 500
                assert datetime.fromisoformat(second.json()["consumed_at"]).tzinfo is not None
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db_session, None)
            await transaction.rollback()
