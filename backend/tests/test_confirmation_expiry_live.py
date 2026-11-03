"""Opt-in real local API recovery with disposable synthetic meal data."""

import json
import os
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest, NutritionItemInput
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1", reason="Opt-in running local API"
)


@pytest.mark.asyncio(loop_scope="session")
async def test_expired_date_card_recovers_and_applies_once(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    source = datetime.now(CHINA_TIMEZONE).date() - timedelta(days=1)
    target = source - timedelta(days=1)
    async with SessionFactory() as session:
        service = NutritionService(SqlAlchemyNutritionRepository(session))
        for kind, hour in [("lunch", 12), ("dinner", 18)]:
            await service.create_entry(user_id, NutritionEntryCreateRequest(
                meal_type=kind, eaten_at=datetime.combine(source, time(hour), CHINA_TIMEZONE),
                items=[NutritionItemInput(
                    name="过期恢复验收米饭", amount_g=200, basis_amount_g=100,
                    kcal=130, protein_g=3, carbs_g=28, fat_g=1,
                    source="model_estimated", confidence="low",
                )],
            ))
        await session.commit()
    evidence = []
    conversation = (await client.post("/agent/conversations", json={})).json()["id"]
    message = f"{source.day}号的饮食记错了应该是{target.day}号的"

    async def chat():
        response = await client.post("/agent/chat", json={
            "message": message, "conversation_id": conversation,
            "context_hints": {
                "timezone": "Asia/Shanghai", "occurred_at": datetime.now(UTC).isoformat(),
            },
        })
        payload = response.json()
        evidence.append({"http_status": response.status_code, "response": payload})
        (ROOT / ".local" / "confirmation-expiry-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        assert response.status_code == 200 and payload["status"] == "completed"
        assert len(payload["confirmation_cards"]) == 1
        return payload["confirmation_cards"][0]

    old = await chat()
    original = (await client.get("/nutrition/entries", params={"date": source.isoformat()})).json()
    async with SessionFactory() as session:
        row = await session.get(Confirmation, UUID(old["confirmation_id"]))
        assert row.user_id == user_id
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    denied = await client.post(f"/confirmations/{old['confirmation_id']}/approve",
        json={"expected_version": old["version"]}, headers={"Idempotency-Key": str(uuid4())})
    assert denied.status_code == 409
    status = (await client.get(f"/confirmations/{old['confirmation_id']}")).json()
    assert status["status"] == "expired"
    fresh = await chat()
    assert fresh["confirmation_id"] != old["confirmation_id"] and fresh["status"] == "pending"
    assert datetime.fromisoformat(fresh["expires_at"].replace("Z", "+00:00")) > datetime.now(UTC)
    unchanged = await client.get("/nutrition/entries", params={"date": source.isoformat()})
    assert unchanged.json() == original
    key = str(uuid4())
    for _ in range(2):
        approved = await client.post(f"/confirmations/{fresh['confirmation_id']}/approve",
            json={"expected_version": fresh["version"]}, headers={"Idempotency-Key": key})
        assert approved.status_code == 200 and approved.json()["status"] == "succeeded"
    moved = (await client.get("/nutrition/entries", params={"date": target.isoformat()})).json()
    assert {e["id"] for e in moved} == {e["id"] for e in original}
    assert all(e["version"] == 2 for e in moved)
    source_entries = await client.get("/nutrition/entries", params={"date": source.isoformat()})
    assert source_entries.json() == []
