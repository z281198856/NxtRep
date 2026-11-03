"""Real-model acceptance using the existing disposable-account fixture."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1", reason="Opt-in real model"
)


@pytest.mark.asyncio(loop_scope="session")
async def test_water_clarify_revise_query_confirm_and_history(live_account):  # noqa: F811
    client, _, *_ = live_account
    events = []
    conversation_id = None
    day = (datetime.now(CHINA_TIMEZONE).date() - timedelta(days=1)).isoformat()

    async def chat(message):
        nonlocal conversation_id
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
        event = {"request": message, "http_status": response.status_code, "response": payload}
        events.append(event)
        if payload.get("run_id"):
            async with SessionFactory() as session:
                run = await session.get(AgentRun, UUID(payload["run_id"]))
                event["plan"] = run.checkpoint.get("action_plan")
                event["tools"] = run.checkpoint.get("tool_runs")
        (ROOT / ".local/water-agent-live.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert response.status_code == 200, "Inspect water-agent-live.json"
        assert payload["status"] != "failed", "Inspect water-agent-live.json"
        conversation_id = payload["conversation_id"]
        return payload

    initial = await chat("帮我补记昨天喝的一杯白水。")
    assert initial["status"] == "needs_input" and not initial["confirmation_cards"]
    clarified = await chat("这一杯是250毫升。")
    cards = clarified["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == "water_entry_create"
    original = cards[0]
    assert original["after"]["water"]["amount_ml"] == 250
    assert (
        datetime.fromisoformat(original["after"]["water"]["consumed_at"])
        .astimezone(CHINA_TIMEZONE)
        .date()
        .isoformat()
        == day
    )
    assert (await client.get("/nutrition/water", params={"date": day})).json() == []
    query = await chat("先查昨天已经记了多少饮水，刚才那杯先别保存。")
    assert not query["confirmation_cards"]
    assert any(tool.get("tool_name") == "read_water_entries" for tool in events[-1]["tools"])
    revised = await chat("刚才那杯改成500毫升，还是昨天的，先给我确认。")
    card = revised["confirmation_cards"][0]
    assert (
        card["operation_type"] == "water_entry_create"
        and card["after"]["water"]["amount_ml"] == 500
    )
    assert card["after"]["replaces_confirmation_id"] == original["confirmation_id"]
    headers = {"Idempotency-Key": str(uuid4())}
    for _ in range(2):
        approval = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            headers=headers,
            json={"expected_version": card["version"]},
        )
        assert approval.status_code == 200, approval.text
    entries = (await client.get("/nutrition/water", params={"date": day})).json()
    assert len(entries) == 1 and entries[0]["amount_ml"] == 500
    summary = (await client.get("/nutrition/daily-summary", params={"date": day})).json()
    assert summary["water_ml"] == 500 and float(summary["consumed"]["kcal"]) == 0
