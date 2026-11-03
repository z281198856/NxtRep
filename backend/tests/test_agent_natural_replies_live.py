"""Opt-in real model/API checks using a disposable account, never the App account."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentConversation, AgentRun, NutritionEntry, Workout
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1",
    reason="Opt-in real-model/API test with a disposable account",
)
EVIDENCE = ROOT / ".local/natural-replies-live.json"


async def chat(client, message, conversation_id=None):
    response = await client.post("/agent/chat", json={
        "message": message, "conversation_id": conversation_id, "client_turn_id": str(uuid4()),
        "context_hints": {
            "timezone": "Asia/Shanghai", "occurred_at": datetime.now(UTC).isoformat(),
        },
    })
    payload = response.json()
    if response.status_code != 200:
        events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
        events.append({"message": message, "http_status": response.status_code, "error": payload})
        EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    assert response.status_code == 200, "Inspect natural-replies-live.json for the actual error"
    async with SessionFactory() as session:
        run = await session.get(AgentRun, UUID(payload["run_id"]))
        conversation = await session.get(AgentConversation, UUID(payload["conversation_id"]))
        event = {"message": message, "response": payload, "plan": run.checkpoint.get("action_plan"),
                 "task_state": conversation.task_state}
    events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    events.append(event)
    EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, event


@pytest.mark.asyncio(loop_scope="session")
async def test_real_user_phased_workout_then_complete_details(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    async with SessionFactory() as session:
        before = await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        ))
    first, observed = await chat(
        client, "今天练了胸先帮我创建一个训练记录我再告诉你练了什么",
    )
    assert first["status"] == "needs_input", "Inspect natural-replies-live.json"
    assert not first["confirmation_cards"]
    assert "等你" in first["message"]
    assert not any(word in first["message"] for word in ("请补充", "公斤", "几组", "已保存"))
    task_id = observed["task_state"]["active_task"]["task_id"]
    final, observed = await chat(
        client, "杠铃卧推60公斤，四组，每组8次，先给草稿", first["conversation_id"],
    )
    assert final["status"] == "completed" and len(final["confirmation_cards"]) == 1
    assert observed["task_state"]["active_task"]["task_id"] == task_id
    assert final["confirmation_cards"][0]["operation_type"] == "workout_record_create"
    assert "确认生效" not in final["message"]
    async with SessionFactory() as session:
        after = await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        ))
    assert after == before, "Draft must not create formal workout data"


@pytest.mark.asyncio(loop_scope="session")
async def test_plan_deferral_is_understood_without_generating_default_plan(live_account):  # noqa:F811
    client, *_ = live_account
    payload, observed = await chat(client, "先创建一个训练计划，具体训练内容我等下再告诉你。")
    assert payload["status"] == "needs_input" and not payload["confirmation_cards"]
    task = observed["task_state"]["active_task"]
    assert task["task_type"] == "training_plan_draft"
    assert task["current_step"] == "await_user_details"
    assert "等你" in payload["message"]
    assert not any(word in payload["message"] for word in ("几组", "公斤", "已创建", "失败"))


@pytest.mark.asyncio(loop_scope="session")
async def test_meal_draft_reply_is_concise_but_status_query_remains_truthful(live_account):  # noqa:F811
    client, user_id, *_ = live_account
    async with SessionFactory() as session:
        before = await session.scalar(select(func.count()).select_from(NutritionEntry).where(
            NutritionEntry.user_id == user_id,
        ))
    first, _ = await chat(client, "记录今天午饭：熟米饭200克，鸡胸肉150克。")
    assert first["status"] == "completed" and len(first["confirmation_cards"]) == 1
    assert "草稿" in first["message"]
    assert not any(word in first["message"] for word in (
        "正式记录", "批准后", "确认后才", "生效", "不受影响",
    )), "Inspect natural-replies-live.json"
    status, _ = await chat(client, "这份草稿现在算正式记录吗？", first["conversation_id"])
    assert status["status"] == "completed" and not status["confirmation_cards"]
    assert any(word in status["message"] for word in ("尚未", "还没", "待确认"))
    assert "pending" not in status["message"] and "过期" not in status["message"]
    async with SessionFactory() as session:
        after = await session.scalar(select(func.count()).select_from(NutritionEntry).where(
            NutritionEntry.user_id == user_id,
        ))
    assert before == after
