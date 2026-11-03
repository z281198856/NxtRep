"""Opt-in real API/model acceptance on a disposable account, never the user's meals."""

import json
import os
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest, NutritionItemInput
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1", reason="Opt-in real model/local API"
)


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_date_correction_revision_and_ambiguous_followup(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    today = datetime.now(CHINA_TIMEZONE).date()
    source, target, corrected = (today - timedelta(days=n) for n in (1, 2, 3))
    evidence = []
    async with SessionFactory() as session:
        service = NutritionService(SqlAlchemyNutritionRepository(session))
        for kind, hour in [("lunch", 12), ("dinner", 18)]:
            await service.create_entry(
                user_id,
                NutritionEntryCreateRequest(
                    meal_type=kind,
                    eaten_at=datetime.combine(source, time(hour), CHINA_TIMEZONE),
                    items=[
                        NutritionItemInput(
                            name="日期更正验收米饭",
                            amount_g=200,
                            basis_amount_g=100,
                            kcal=130,
                            protein_g=3,
                            carbs_g=28,
                            fat_g=1,
                            source="user_confirmed",
                            confidence="medium",
                        )
                    ],
                ),
            )
        await session.commit()
    conversation = (await client.post("/agent/conversations", json={})).json()["id"]

    async def chat(message):
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation,
                "context_hints": {
                    "timezone": "Asia/Shanghai",
                    "occurred_at": datetime.now(UTC).isoformat(),
                },
            },
        )
        payload = response.json()
        evidence.append(
            {"message": message, "http_status": response.status_code, "response": payload}
        )
        (ROOT / ".local" / "meal-date-change-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        assert response.status_code == 200, "Inspect .local/meal-date-change-live.json"
        return payload

    def only_card(payload):
        assert payload["status"] == "completed", "Inspect .local/meal-date-change-live.json"
        assert len(payload["confirmation_cards"]) == 1
        card = payload["confirmation_cards"][0]
        assert card["operation_type"] == "nutrition_entries_date_change"
        return card

    first = only_card(await chat(f"{source.day}号的饮食记错了应该是{target.day}号的"))
    assert first["after"]["request"]["source_date"] == source.isoformat()
    assert first["after"]["request"]["target_date"] == target.isoformat()
    assert len(first["after"]["request"]["entries"]) == 2
    original = (await client.get("/nutrition/entries", params={"date": source.isoformat()})).json()
    assert len(original) == 2
    revised = only_card(await chat(f"不对，应该是{corrected.day}号"))
    assert revised["after"]["replaces_confirmation_id"] == first["confirmation_id"]
    assert revised["after"]["request"]["target_date"] == corrected.isoformat()
    assert (
        await client.get("/nutrition/entries", params={"date": source.isoformat()})
    ).json() == original
    approval = await client.post(
        f"/confirmations/{revised['confirmation_id']}/approve",
        json={"expected_version": revised["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approval.status_code == 200
    moved = (await client.get("/nutrition/entries", params={"date": corrected.isoformat()})).json()
    assert {e["id"] for e in moved} == {e["id"] for e in original}
    # A fresh task has two plausible meals; a bare yes must not pick one.
    conversation = (await client.post("/agent/conversations", json={})).json()["id"]
    ambiguous = await chat(f"{corrected.day}号有一餐的日期记错了，应该是{target.day}号的")
    assert ambiguous["status"] == "needs_input" and not ambiguous["confirmation_cards"]
    yes = await chat("是的")
    assert yes["status"] == "needs_input" and not yes["confirmation_cards"]
    selected = only_card(await chat("午饭"))
    assert len(selected["after"]["request"]["entries"]) == 1
    assert selected["after"]["preview"]["entries"][0]["meal_type"] == "lunch"
