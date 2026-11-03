"""Verify history copying and water confirmation with isolated, rolled-back users."""

import os
from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import pytest

from nxtrep_backend.agents.tools import AgentToolContext, build_tools, groups_for_task
from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import SessionFactory, get_db_session
from nxtrep_backend.main import app
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.water import SqlAlchemyWaterRepository
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.water import WaterService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_recent_copy_is_owned_versioned_idempotent_and_preserves_snapshot():
    async with SessionFactory() as session:
        owner = User(username=f"copy-{uuid4().hex}", password_setup_required=False)
        other = User(username=f"other-copy-{uuid4().hex}", password_setup_required=False)
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
                original = await client.post(
                    "/api/v1/nutrition/entries",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={
                        "meal_type": "lunch",
                        "eaten_at": "2026-10-22T12:00:00+08:00",
                        "items": [
                            {
                                "name": "测试米饭",
                                "amount_g": 150,
                                "basis_amount_g": 100,
                                "kcal": 120,
                                "protein_g": 3,
                                "carbs_g": 25,
                                "fat_g": 1,
                                "source": "user",
                                "confidence": "confirmed",
                            }
                        ],
                    },
                )
                assert original.status_code == 201, original.text
                source = original.json()
                path = f"/api/v1/nutrition/entries/{source['id']}/copy"
                headers = {"Idempotency-Key": str(uuid4())}
                body = {
                    "expected_version": source["version"],
                    "meal_type": "breakfast",
                    "eaten_at": "2026-10-23T08:00:00+08:00",
                }
                copied = await client.post(path, headers=headers, json=body)
                assert copied.status_code == 201, copied.text
                assert copied.json()["items"] == source["items"]
                assert copied.json()["totals"] == source["totals"]
                assert copied.json()["id"] != source["id"]
                assert (await client.post(path, headers=headers, json=body)).json() == copied.json()
                recent = (
                    await client.get("/api/v1/nutrition/entries/recent?date=2026-10-22")
                ).json()
                assert [item["id"] for item in recent] == [source["id"]]
                summary = (
                    await client.get("/api/v1/nutrition/daily-summary?date=2026-10-23")
                ).json()
                assert summary["recorded_meals"] == ["breakfast"]
                assert float(summary["consumed"]["kcal"]) == 180
                assert (
                    await client.post(
                        path,
                        headers={"Idempotency-Key": str(uuid4())},
                        json={**body, "expected_version": 999},
                    )
                ).status_code == 409
                current = other
                assert (
                    await client.get("/api/v1/nutrition/entries/recent?date=2026-10-23")
                ).json() == []
                assert (
                    await client.post(path, headers={"Idempotency-Key": str(uuid4())}, json=body)
                ).status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db_session, None)
            await session.rollback()


@pytest.mark.asyncio
async def test_water_propose_revise_approve_once_and_cancel_without_writing():
    async with SessionFactory() as session:
        try:
            user = User(username=f"water-agent-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            confirmations = SqlAlchemyConfirmationRepository(session)
            water = WaterService(SqlAlchemyWaterRepository(session), confirmations)
            confirm = DatabaseConfirmationService(confirmations)
            context = AgentToolContext(
                user_id=user.id,
                profile_service=MagicMock(),
                goals_service=MagicMock(),
                exercises_service=MagicMock(),
                training_service=MagicMock(),
                workout_service=MagicMock(),
                nutrition_service=MagicMock(),
                body_service=MagicMock(),
                memory_service=MagicMock(),
                confirmation_service=confirm,
                water_service=water,
                task_type="water_record_draft",
            )
            task = AgentIntentTask(
                task_type="water_record_draft",
                confidence="high",
                routing_reason="explicit water record",
            )
            tools = {tool.name: tool for tool in build_tools(context, groups=groups_for_task(task))}
            args = {"amount_ml": 250, "consumed_at": "2026-10-22T16:00:00Z"}
            proposed = await tools["propose_water_entry"].ainvoke(args)
            assert proposed["status"] == "confirmation_required", proposed
            assert await tools["propose_water_entry"].ainvoke(args) == proposed
            assert (await water.summary(user.id, date(2026, 10, 23)))["water_ml"] == 0
            old_id = UUID(proposed["confirmation"]["confirmation_id"])
            scoped = replace(context, task_scope={"confirmation_id": str(old_id)})
            revision_tools = {
                tool.name: tool for tool in build_tools(scoped, groups=groups_for_task(task))
            }
            blocked = await revision_tools["propose_water_entry"].ainvoke(
                {**args, "amount_ml": 500}
            )
            assert blocked["status"] == "needs_review"
            revised = await revision_tools["propose_pending_draft_revision"].ainvoke(
                {
                    "confirmation_id": str(old_id),
                    "expected_version": 1,
                    "changes": {"amount_ml": 500},
                }
            )
            assert revised["status"] == "confirmation_required", revised
            card = revised["confirmation"]
            assert (
                card["after"]["water"]["consumed_at"]
                == proposed["confirmation"]["after"]["water"]["consumed_at"]
            )
            with pytest.raises(DatabaseConfirmationConflictError):
                await confirm.approve(user.id, old_id, 1)
            await confirm.approve(user.id, UUID(card["confirmation_id"]), card["version"])
            with pytest.raises(DatabaseConfirmationConflictError):
                await confirm.approve(user.id, UUID(card["confirmation_id"]), card["version"])
            read = await tools["read_water_entries"].ainvoke({"day": "2026-10-23"})
            assert read["water_ml"] == 500 and len(read["entries"]) == 1
            assert (await water.summary(user.id, date(2026, 10, 22)))["water_ml"] == 0
            cancelled = await tools["propose_water_entry"].ainvoke({**args, "amount_ml": 300})
            card = cancelled["confirmation"]
            await confirm.reject(user.id, UUID(card["confirmation_id"]), card["version"], "取消")
            assert (await water.summary(user.id, date(2026, 10, 23)))["water_ml"] == 500
        finally:
            await session.rollback()
