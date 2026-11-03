"""Opt-in local API acceptance using only a disposable account and synthetic meals."""

import json
import os
from datetime import UTC, datetime, time, timedelta

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
async def test_query_interruption_resume_and_explicit_meal_scope(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    source = datetime.now(CHINA_TIMEZONE).date() - timedelta(days=2)
    target = source - timedelta(days=1)
    evidence = []
    async with SessionFactory() as session:
        service = NutritionService(SqlAlchemyNutritionRepository(session))
        for kind, hour in [("breakfast", 8), ("lunch", 12), ("dinner", 18)]:
            await service.create_entry(user_id, NutritionEntryCreateRequest(
                meal_type=kind,
                eaten_at=datetime.combine(source, time(hour), CHINA_TIMEZONE),
                items=[NutritionItemInput(
                    name="熟米饭", amount_g=200, basis_amount_g=100, kcal=130,
                    protein_g=3, carbs_g=28, fat_g=1,
                    source="user_confirmed", confidence="medium",
                )],
            ))
        await session.commit()
    original = (await client.get("/nutrition/entries", params={"date": source.isoformat()})).json()
    assert len(original) == 3

    async def chat(message, conversation_id=None):
        response = await client.post("/agent/chat", json={
            "message": message, "conversation_id": conversation_id,
            "context_hints": {
                "timezone": "Asia/Shanghai", "occurred_at": datetime.now(UTC).isoformat(),
            },
        })
        payload = response.json()
        evidence.append({
            "message": message, "http_status": response.status_code, "response": payload,
        })
        (ROOT / ".local" / "agent-language-api-live.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        assert response.status_code == 200, "Inspect agent-language-api-live.json"
        assert payload["status"] in {"completed", "needs_input"}, (
            "Inspect agent-language-api-live.json"
        )
        print(json.dumps({"message": message, "tasks": [
            b["task_type"] for b in payload["analysis_results"]
        ], "cards": len(payload["confirmation_cards"])}, ensure_ascii=False), flush=True)
        return payload

    query = await chat("看看前天饮食多少热量")
    assert query["status"] == "completed"
    assert query["analysis_results"][0]["task_type"] == "structured_data_query"
    assert "780" in query["message"]
    assert not query["confirmation_cards"]
    food = await chat("鸡腿饭多少热量")
    assert food["analysis_results"][0]["task_type"] == "general_question"
    assert not food["confirmation_cards"]
    assert "千卡" in food["message"] or "大卡" in food["message"]

    choosing = await chat(f"把{source.isoformat()}的一餐饮食改到{target.isoformat()}")
    assert choosing["status"] == "needs_input"
    assert not choosing["confirmation_cards"]
    conversation = choosing["conversation_id"]
    question = await chat("这个米饭多少热量？", conversation)
    assert not question["confirmation_cards"]
    assert all(b["task_type"] == "structured_data_query" for b in question["analysis_results"])
    if question["status"] == "completed":
        assert "260" in question["message"] or any(
            text in question["message"]
            for text in ("哪一餐", "哪餐", "哪一份", "哪份", "早餐、午饭")
        ), "Read the actual portion or clarify the ambiguous meal"
    assert "补查完" not in question["message"]
    assert "training_plan_activate" not in question["message"]
    resumed = await chat("继续刚才的任务", conversation)
    assert not resumed["confirmation_cards"]
    selected = await chat("午饭", conversation)
    cards = selected["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "nutrition_entries_date_change"
    assert len(cards[0]["after"]["request"]["entries"]) == 1
    focused_query = await chat("这餐米饭多少热量？", conversation)
    assert focused_query["status"] == "completed"
    assert "260" in focused_query["message"]
    assert not focused_query["confirmation_cards"]
    assert any(
        run["tool_name"] == "read_nutrition_entries"
        for branch in focused_query["analysis_results"] for run in branch["tool_runs"]
    )

    multiple = await chat(f"把{source.isoformat()}午饭和晚饭改到{target.isoformat()}，早餐不动")
    cards = multiple["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "nutrition_entries_date_change"
    assert {e["entry_id"] for e in cards[0]["after"]["request"]["entries"]} == {
        e["id"] for e in original if e["meal_type"] in {"lunch", "dinner"}
    }
    current_source = await client.get("/nutrition/entries", params={"date": source.isoformat()})
    current_target = await client.get("/nutrition/entries", params={"date": target.isoformat()})
    assert current_source.json() == original
    assert current_target.json() == []
