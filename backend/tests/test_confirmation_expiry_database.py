"""Real transaction rollback, status readback, and fresh date-draft recovery."""

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from test_agent_multiturn_pipeline import tool_context
from test_meal_date_change_database import prepare

from nxtrep_backend.agents.tools import build_tools
from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import Confirmation, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app
from nxtrep_backend.schemas.nutrition import NutritionDateChangeRequest
from nxtrep_backend.services.confirmation import DatabaseConfirmationService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_expired_approval_rollback_then_get_reports_expired_once_and_never_moves_meals():
    user_id = None
    previous = dict(app.dependency_overrides)
    try:
        async with SessionFactory() as session:
            user, service, _, entries, _, body = await prepare(session)
            user_id = user.id
            old = await service.propose_saved_date_change(user.id, body)
            old.expires_at = datetime.now(UTC) - timedelta(hours=1)
            old_id, version = old.id, old.version
            original = [deepcopy(service._entry_snapshot(e)) for e in entries]
            entry_ids = [e.id for e in entries]
            await session.commit()
        app.dependency_overrides[get_current_user] = lambda: user
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            approval = await client.post(f"/api/v1/confirmations/{old_id}/approve",
                json={"expected_version": version}, headers={"Idempotency-Key": str(uuid4())})
            assert approval.status_code == 409
            assert "expired" in approval.json()["error"]["message"].casefold()
            for _ in range(2):
                response = await client.get(f"/api/v1/confirmations/{old_id}")
                assert response.status_code == 200
                assert response.json()["status"] == "expired"
                assert response.json()["version"] == version + 1
            pending = await client.get("/api/v1/confirmations", params={"status": "pending"})
            assert all(c["id"] != str(old_id) for c in pending.json()["list"])
        async with SessionFactory() as session:
            saved = await session.get(Confirmation, old_id)
            assert saved.status == "expired" and saved.executed_at is None
            from nxtrep_backend.db.models import NutritionEntry

            for entry_id, snapshot in zip(entry_ids, original, strict=True):
                entry = await session.get(NutritionEntry, entry_id)
                current = service._entry_snapshot(entry)
                assert datetime.fromisoformat(current.pop("eaten_at")) == datetime.fromisoformat(
                    snapshot["eaten_at"]
                )
                assert current == {k: v for k, v in snapshot.items() if k != "eaten_at"}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        if user_id:
            async with SessionFactory() as session:
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()


@pytest.mark.asyncio
async def test_expired_draft_recovery_revalidates_versions_and_keeps_confirmation_required():
    async with SessionFactory() as session:
        try:
            user, service, repo, entries, _, body = await prepare(session)
            old = await service.propose_saved_date_change(user.id, body)
            old.expires_at = datetime.now(UTC) - timedelta(hours=1)
            entries[0].version += 1
            await session.flush()
            original = [deepcopy(service._entry_snapshot(e)) for e in entries]
            context = tool_context(user_id=user.id, nutrition_service=service,
                confirmation_service=DatabaseConfirmationService(repo))
            from dataclasses import replace

            tools = {t.name: t for t in build_tools(
                replace(context, task_scope={"confirmation_id": str(old.id)}),
                groups={"nutrition_changes"},
            )}
            read = await tools["read_saved_meal_for_change"].ainvoke({
                "day": body.source_date.isoformat(), "all_meals": True,
            })
            fresh = NutritionDateChangeRequest(**{
                **body.model_dump(mode="json"), "entries": [
                    {"entry_id": e["entry_id"], "expected_version": e["version"]}
                    for e in read["selected_entries"]
                ],
            })
            args = {"request": fresh.model_dump(mode="json")}
            first = await tools["propose_saved_meals_date_change"].ainvoke(args)
            second = await tools["propose_saved_meals_date_change"].ainvoke(args)
            assert first == second and first["status"] == "confirmation_required"
            from uuid import UUID

            new = await session.get(Confirmation, UUID(first["confirmation"]["confirmation_id"]))
            assert old.status == "expired" and new.id != old.id and new.status == "pending"
            assert new.expires_at > datetime.now(UTC)
            assert [service._entry_snapshot(e) for e in entries] == original
            await DatabaseConfirmationService(repo).approve(user.id, new.id, new.version)
            assert all(
                e.eaten_at.astimezone(CHINA_TIMEZONE).date() == body.target_date for e in entries
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_foreign_status_read_cannot_expire_another_users_card():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, _, body = await prepare(session)
            old = await service.propose_saved_date_change(user.id, body)
            old.expires_at = datetime.now(UTC) - timedelta(hours=1)
            await session.flush()
            assert await repo.get_confirmation(uuid4(), old.id) is None
            await session.refresh(old)
            assert old.status == "pending" and old.version == 1
        finally:
            await session.rollback()
