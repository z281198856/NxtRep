"""Opt-in model/API regression; only the disposable fixture account is mutated."""

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.models import AgentRun, NutritionEntry, WorkoutSet
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.providers.models import build_intent_router_model
from nxtrep_backend.schemas.agent import AgentContextHints
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_AGENT_GAP_LIVE_TESTS") != "1",
    reason="Opt-in real model with running local API and disposable account",
)
EVIDENCE = ROOT / ".local" / "agent-gap-fix-live.json"


def record(event, **data):
    events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    events.append({"event": event, **data})
    EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


async def chat(client, message, conversation_id=None):
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
    record("chat", request=message, http_status=response.status_code, response=payload)
    assert response.status_code == 200, "Inspect agent-gap-fix-live.json"
    async with SessionFactory() as session:
        run = await session.get(AgentRun, UUID(payload["run_id"]))
        record(
            "trace", plan=run.checkpoint.get("action_plan"), tools=run.checkpoint.get("tool_runs")
        )
    assert payload["status"] == "completed", "Inspect agent-gap-fix-live.json"
    assert len(payload["confirmation_cards"]) == 1, "Inspect agent-gap-fix-live.json"
    return payload


async def approve(client, card):
    response = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={"expected_version": card["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, "Synthetic account approval failed"
    return response.json()


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_reference_addition_and_pending_food_replacement(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    first = await chat(
        client,
        "记录今天晚饭：葱烧去皮鸡腿肉150克、炒空心菜150克、熟米饭190克。"
        "按常见成品营养估算，给待确认草稿。",
    )
    await approve(client, first["confirmation_cards"][0])
    async with SessionFactory() as session:
        original = await session.scalar(
            select(NutritionEntry).where(
                NutritionEntry.user_id == user_id, NutritionEntry.meal_type == "dinner"
            )
        )
        original_id, original_items = original.id, original.items
    second = await chat(
        client, "昨天晚上跟今天晚上一样，不过多加了一碗肉沫蒸蛋", first["conversation_id"]
    )
    card = second["confirmation_cards"][0]
    items = card["after"]["preview"]["items"]
    assert len(items) == 4 and any("米饭" in f["name"] for f in items)
    assert any("蒸蛋" in f["name"] for f in items)
    assert all(item in items for item in original_items), "Source snapshots must be retained"
    third = await chat(
        client,
        "这份还没确认的晚饭，蒸蛋换成清炒西兰花，其他不动，没称重就按一小碗估算。",
        first["conversation_id"],
    )
    revised = third["confirmation_cards"][0]
    assert revised["after"]["replaces_confirmation_id"] == card["confirmation_id"]
    assert len(revised["after"]["preview"]["items"]) == 4
    assert any("西兰花" in f["name"] for f in revised["after"]["preview"]["items"])
    assert not any("蒸蛋" in f["name"] for f in revised["after"]["preview"]["items"])
    await approve(client, revised)
    async with SessionFactory() as session:
        source = await session.get(NutritionEntry, original_id)
        assert source.items == original_items and source.version == 1
        rows = list(
            await session.scalars(
                select(NutritionEntry).where(
                    NutritionEntry.user_id == user_id, NutritionEntry.meal_type == "dinner"
                )
            )
        )
        assert len(rows) == 2 and sorted(len(row.items) for row in rows) == [3, 4]
    record("meal_verified", source_retained=True, copied_item_count=4, replacement_scoped=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_weight_and_count_correction_are_both_executed(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    first = await chat(client, "帮我记录今天杠铃卧推60公斤，四组，每组8次，先给草稿。")
    await approve(client, first["confirmation_cards"][0])
    corrected = await chat(client, "不对，重量是55公斤，实际只做了三组。", first["conversation_id"])
    draft = corrected["confirmation_cards"][0]
    assert draft["operation_type"] == "workout_record_update"
    request = draft["after"]["request"]
    assert request["sets"] == 3 and Decimal(str(request["weight_kg"])) == 55
    assert len(draft["after"]["preview"]["after_sets"]) == 3
    await approve(client, draft)
    async with SessionFactory() as session:
        rows = list(
            await session.scalars(
                select(WorkoutSet).where(
                    WorkoutSet.workout_id == UUID(draft["after"]["workout_id"])
                )
            )
        )
        effective = [row for row in rows if row.voided_at is None]
        assert len(effective) == 3 and all(row.weight_kg == 55 for row in effective)
        assert len(rows) == 4 and sum(row.voided_at is not None for row in rows) == 1
    record("workout_verified", effective_sets=3, weight_kg=55, history_retained=True)


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_resumes_earlier_task_and_changes_date_without_old_session():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    workout_id = str(uuid4())
    state = TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        {
            "transition": "new",
            "entities": {"workout_id": workout_id},
            "parameters": {
                "exercise_name": "卧推",
                "weight_kg": 60,
                "workout_date": today.isoformat(),
            },
        },
    )
    task_id = state.active_task.task_id
    state = TaskStateManager.apply_plan(
        state,
        "nutrition_record_draft",
        {
            "transition": "new",
            "parameters": {"meal_type": "lunch"},
        },
    )
    state = TaskStateManager.apply_plan(state, "training_plan_draft", {"transition": "new"})
    router = AgentIntentRouter(build_intent_router_model(get_settings()))
    first = await router.route(
        message="继续刚才还没记完的卧推，是四组，每组八次。",
        images=[],
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
        context_hints=AgentContextHints(timezone="Asia/Shanghai", occurred_at=datetime.now(UTC)),
    )
    record("resume_plan", plan=first.model_dump(mode="json"))
    task = first.tasks[0]
    assert task.task_type == "workout_record_draft" and task.task_update.transition == "resume"
    state = TaskStateManager.apply_plan(state, task.task_type, task.task_update)
    assert state.active_task.task_id == task_id
    assert state.active_task.parameters["weight_kg"] == "60"
    assert state.active_task.parameters["sets"] == 4 and state.active_task.parameters["reps"] == 8
    second = await router.route(
        message="再补记昨天的上斜卧推，20公斤，三组每组十次。",
        images=[],
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
        context_hints=AgentContextHints(timezone="Asia/Shanghai", occurred_at=datetime.now(UTC)),
    )
    record("new_date_plan", plan=second.model_dump(mode="json"))
    task = second.tasks[0]
    assert task.task_type == "workout_record_draft" and task.task_update.transition == "new"
    state = TaskStateManager.apply_plan(state, task.task_type, task.task_update)
    assert state.active_task.parameters["workout_date"] == (today - timedelta(days=1)).isoformat()
    assert "workout_id" not in state.active_task.entities
    record("task_state_verified", original_task_restored=True, old_session_not_inherited=True)
