"""Opt-in meal estimation acceptance using the existing disposable live account."""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentConversation, NutritionEntry
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_MEAL_ESTIMATION_LIVE_TESTS") != "1",
    reason="Opt-in only: calls the configured model and already-running local API",
)


@pytest.mark.asyncio(loop_scope="session")
async def test_unweighed_lunch_creates_estimated_draft_then_revises_same_meal(live_account):  # noqa: F811
    client, user_id, _, _, _ = live_account
    evidence = []
    conversation = await client.post("/agent/conversations", json={})
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]

    async def entry_count():
        async with SessionFactory() as session:
            return await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user_id)
            )

    async def chat(message):
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
                "client_turn_id": str(uuid4()),
                "context_hints": {
                    "timezone": "Asia/Shanghai",
                    "occurred_at": datetime.now(UTC).isoformat(),
                },
            },
        )
        payload = response.json()
        async with SessionFactory() as session:
            stored_state = await session.scalar(
                select(AgentConversation.task_state).where(
                    AgentConversation.id == UUID(conversation_id),
                    AgentConversation.user_id == user_id,
                )
            )
        evidence.append(
            {
                "message": message,
                "http_status": response.status_code,
                "response": payload,
                "task_state": stored_state,
            }
        )
        (ROOT / ".local" / "meal-estimation-live-20261010.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert response.status_code == 200, "Inspect local meal-estimation acceptance evidence"
        assert payload["status"] == "completed", "Inspect local meal-estimation acceptance evidence"
        assert len(payload["confirmation_cards"]) == 1
        assert payload["confirmation_cards"][0]["operation_type"] == "nutrition_entry_create"
        assert payload["confirmation_cards"][0]["status"] == "pending"
        assert await entry_count() == before, "A draft must not write an eaten meal before approval"
        return payload

    before = await entry_count()
    # Synthetic data only: never resend the user's private meal to an external model.
    first = await chat("帮虚拟测试账号记录这份虚构午餐：番茄炒蛋、清炒西兰花和一碗米饭")
    old_card = first["confirmation_cards"][0]
    items = old_card["after"]["entry"]["items"]
    assert len(items) == 3
    assert all(Decimal(str(item["amount_g"])) > 0 for item in items)
    assert any(word in first["message"] for word in ("估算", "暂按", "暂定", "假设"))
    preview = old_card["after"]["preview"]["items"]
    rice_index = next(index for index, item in enumerate(preview) if "米饭" in item["name"])
    current_amount = Decimal(str(preview[rice_index]["amount_g"]))
    unchanged = await chat(f"米饭改成{current_amount:f}克，番茄炒蛋和西兰花不变")
    same_card = unchanged["confirmation_cards"][0]
    assert same_card["confirmation_id"] == old_card["confirmation_id"]
    same_tools = {
        run["tool_name"]
        for branch in unchanged["analysis_results"]
        for run in branch.get("tool_runs", [])
    }
    assert "propose_nutrition_entry" not in same_tools
    assert "propose_nutrition_entry_revision" not in same_tools
    revised_amount = current_amount + 50
    revised = await chat(f"米饭改成{revised_amount:f}克，番茄炒蛋和西兰花不变")
    new_card = revised["confirmation_cards"][0]
    assert new_card["confirmation_id"] != old_card["confirmation_id"]
    assert new_card["after"]["replaces_confirmation_id"] == old_card["confirmation_id"]
    tool_names = {
        run["tool_name"]
        for branch in revised["analysis_results"]
        for run in branch.get("tool_runs", [])
    }
    assert "propose_nutrition_entry_revision" in tool_names
    assert "propose_nutrition_entry" not in tool_names
    new_preview = new_card["after"]["preview"]["items"]
    assert Decimal(str(new_preview[rice_index]["amount_g"])) == revised_amount
    for index, item in enumerate(preview):
        if index != rice_index:
            assert new_preview[index] == item
    response = await client.get(f"/confirmations/{old_card['confirmation_id']}")
    assert response.status_code == 200
    assert response.json()["status"] != "pending"
