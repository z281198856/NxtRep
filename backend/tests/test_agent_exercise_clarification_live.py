"""Real App phrasing through the API, restricted to disposable accounts."""

import json
import os
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentConversation, AgentRun, Workout
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1",
    reason="Opt-in real model/API acceptance with a disposable account",
)
EVIDENCE = ROOT / ".local/exercise-clarification-live.json"


async def chat(client, message, conversation_id=None):
    response = await client.post("/agent/chat", json={
        "message": message, "conversation_id": conversation_id, "client_turn_id": str(uuid4()),
        "context_hints": {
            "timezone": "Asia/Shanghai", "occurred_at": datetime.now(UTC).isoformat(),
        },
    })
    payload = response.json()
    events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    event = {"request": message, "http_status": response.status_code, "response": payload}
    if response.status_code == 200:
        async with SessionFactory() as session:
            run = await session.get(AgentRun, UUID(payload["run_id"]))
            conversation = await session.get(AgentConversation, UUID(payload["conversation_id"]))
            event.update(task_state=conversation.task_state, plan=run.checkpoint.get("action_plan"),
                         tools=run.checkpoint.get("tool_runs"))
    events.append(event)
    EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    assert response.status_code == 200, "Inspect exercise-clarification-live.json"
    return payload, event


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("selection", [
    pytest.param("杠铃的", id="legacy_equipment"),
    pytest.param("第一个", id="ordinal"),
    pytest.param("第二个", id="displayed_ordinal"),
    pytest.param("我是躺在平凳上推杠铃的那种", id="semantic"),
])
async def test_real_short_exercise_name_then_selection_keeps_all_details(
    live_account, selection,  # noqa: F811
):
    client, user_id, *_ = live_account
    async with SessionFactory() as session:
        before = await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        ))
    start, start_event = await chat(
        client, "今天练的胸先帮我创建一个训练记录，我再告诉你练了什么",
    )
    task_id = start_event["task_state"]["active_task"]["task_id"]
    ambiguous, event = await chat(
        client, "卧推55kg4组每组8次，先列出动作候选让我选，先别生成草稿。",
        start["conversation_id"],
    )
    task = event["task_state"]["active_task"]
    assert ambiguous["status"] == "needs_input" and not ambiguous["confirmation_cards"]
    assert task["task_id"] == task_id and len(task["candidates"]) >= 2
    assert all(c["label"] in ambiguous["message"] for c in task["candidates"])
    assert "失败" not in ambiguous["message"] and "公斤" not in ambiguous["message"]
    if selection in {"第一个", "第二个"}:
        ordinal = 1 if selection == "第一个" else 2
        line = re.search(rf"(?:^|\n)\s*{ordinal}[.、．)）]\s*([^\n]+)", ambiguous["message"])
        assert line, "Ordinal selection must refer to the list actually displayed"
        matches = [c for c in task["candidates"] if c["label"] in line[1]]
        assert len(matches) == 1
        chosen = matches[0]
    else:
        chosen = next(c for c in task["candidates"] if c["label"] == "杠铃卧推")
    if selection == "杠铃的":
        # Reproduce the old persisted shape only in the disposable account.
        # Its authoritative last_tool_result still contains the actual choices.
        async with SessionFactory() as session:
            conversation = await session.get(AgentConversation, UUID(start["conversation_id"]))
            assert conversation.user_id == user_id
            legacy = json.loads(json.dumps(conversation.task_state))
            legacy["active_task"]["candidates"] = []
            legacy["active_task"]["missing_fields"] = ["exercise_id"]
            conversation.task_state = legacy
            await session.commit()
    result, event = await chat(client, selection, start["conversation_id"])
    assert result["status"] == "completed" and len(result["confirmation_cards"]) == 1
    assert event["task_state"]["active_task"]["task_id"] == task_id
    card = result["confirmation_cards"][0]
    assert card["operation_type"] == "workout_record_create"
    request = card["after"]["request"]
    assert request["exercise_id"] == chosen["id"]
    assert float(request["weight_kg"]) == 55 and request["sets"] == 4 and request["reps"] == 8
    async with SessionFactory() as session:
        after = await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        ))
    assert before == after, "User confirmation remains required"
