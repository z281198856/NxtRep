"""Opt-in actual model/API acceptance, using only a disposable synthetic account."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.models import AgentRun, NutritionEntry
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.providers.models import build_intent_router_model
from nxtrep_backend.schemas.agent import AgentContextHints
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState
from nxtrep_backend.services.conversation import AgentConversationContext

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_SEMANTIC_AGENT_LIVE_TESTS") != "1",
    reason="Opt-in actual model and already-running local API",
)
EVIDENCE = ROOT / ".local" / "agent-semantic-live.json"


def record(event, **data):
    events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    events.append({"event": event, **data})
    EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.asyncio(loop_scope="session")
async def test_real_meal_reference_revision_switch_and_read_only_boundaries(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    conversation_id = None

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
        record("chat", request=message, http_status=response.status_code, response=payload)
        assert response.status_code == 200, "Inspect agent-semantic-live.json"
        conversation_id = payload["conversation_id"]
        async with SessionFactory() as session:
            run = await session.get(AgentRun, UUID(payload["run_id"]))
            record("plan", plan=run.checkpoint.get("action_plan"))
        assert payload["status"] != "failed", "Inspect agent-semantic-live.json"
        return payload

    async def approve(card):
        response = await client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, "Synthetic account approval failed"

    async def entries():
        async with SessionFactory() as session:
            rows = list(
                await session.scalars(
                    select(NutritionEntry).where(
                        NutritionEntry.user_id == user_id,
                        NutritionEntry.deleted_at.is_(None),
                    )
                )
            )
            return {
                str(row.id): {
                    "meal_type": row.meal_type,
                    "items": deepcopy(row.items),
                    "date": row.eaten_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                    "version": row.version,
                    "totals": deepcopy(row.totals),
                }
                for row in rows
            }

    first = await chat(
        "今天午饭是葱烧鸡腿肉和虾仁滑蛋，都是小碗菜，米饭正常一盒，"
        "鸡腿去皮。帮我记录，份量按常见情况估算。"
    )
    assert len(first["confirmation_cards"]) == 1
    await approve(first["confirmation_cards"][0])
    original = await entries()
    lunch_id = next(key for key, row in original.items() if row["meal_type"] == "lunch")

    dinner = await chat("晚饭是把虾仁滑蛋换成了炒空心菜，其他一样")
    assert dinner["status"] == "completed" and len(dinner["confirmation_cards"]) == 1
    dinner_card = dinner["confirmation_cards"][0]
    assert dinner_card["operation_type"] == "nutrition_entry_create"
    assert dinner_card["after"]["entry"]["meal_type"] == "dinner"
    assert "补充" not in dinner["message"] and "多少克" not in dinner["message"]
    assert await entries() == original, "Draft must not modify saved lunch"
    revised = await chat("空心菜其实是200克，其他不变")
    assert len(revised["confirmation_cards"]) == 1
    revised_card = revised["confirmation_cards"][0]
    assert revised_card["after"]["replaces_confirmation_id"] == dinner_card["confirmation_id"]
    await approve(revised_card)
    saved = await entries()
    assert len(saved) == len(original) + 1 and saved[lunch_id] == original[lunch_id]
    dinner_id = next(key for key in saved if key not in original)
    assert saved[dinner_id]["meal_type"] == "dinner"
    lunch_items = original[lunch_id]["items"]
    dinner_items = saved[dinner_id]["items"]
    untouched = [item for item in lunch_items if "虾仁" not in item["name"]]
    assert all(item in dinner_items for item in untouched)
    vegetable = next(item for item in dinner_items if "空心菜" in item["name"])
    assert Decimal(vegetable["amount_g"]) == 200

    yesterday = await chat("昨天晚饭也这样吃的，帮我记上")
    assert len(yesterday["confirmation_cards"]) == 1
    copied = yesterday["confirmation_cards"][0]
    assert copied["operation_type"] == "nutrition_entry_create"
    target_day = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    assert copied["after"]["entry"]["eaten_at"].startswith(target_day.isoformat())
    assert await entries() == saved

    query = await chat("先不要保存昨天那份。只看今天已保存的午饭和晚饭，哪个热量低？")
    assert not query["confirmation_cards"] and await entries() == saved
    assert "午" in query["message"] and "晚" in query["message"]

    correction = await chat(
        "今天午饭里的虾仁滑蛋其实是炒空心菜，把午饭原记录改一下，其他不动，份量按原小碗估算。"
    )
    assert len(correction["confirmation_cards"]) == 1
    corrected_card = correction["confirmation_cards"][0]
    assert corrected_card["operation_type"] == "nutrition_entry_update"
    assert corrected_card["after"]["entry_id"] == lunch_id
    await approve(corrected_card)
    final = await entries()
    assert len(final) == len(saved)
    assert final[dinner_id] == saved[dinner_id]
    assert final[lunch_id]["version"] == original[lunch_id]["version"] + 1
    assert any("空心菜" in item["name"] for item in final[lunch_id]["items"])
    record(
        "verified",
        lunch_unchanged_until_explicit_correction=True,
        dinner_added_once=True,
        dinner_revision_scoped=True,
        read_only_unchanged=True,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_interprets_training_switch_correction_and_knowledge():
    exercise_id, workout_id = str(uuid4()), str(uuid4())
    active = AgentTask(
        task_type="workout_record_draft",
        status="completed",
        entities={"workout_id": workout_id, "workout_exercise_id": exercise_id},
        parameters={"exercise_name": "杠铃卧推", "weight_kg": 60, "sets": 4, "reps": 8},
    )
    context = AgentConversationContext(
        task_state=AgentTaskState(active_task=active).model_dump(mode="json")
    )
    router = AgentIntentRouter(build_intent_router_model(get_settings()))
    cases = [
        ("不对，刚才卧推重量是55公斤", {"workout_record_update_draft"}, "correct"),
        ("再加一个上斜卧推，重量组数我还没说", {"workout_record_draft"}, "new"),
        ("对了，一份鸡腿饭大概多少热量？", {"general_question", "knowledge_retrieval"}, None),
        ("只比较我上周和这周的训练量，不要改记录", {"structured_data_query"}, None),
        ("我的食品库添加一个自定义酸奶，每100克60千卡", {"food_catalog_draft"}, None),
        ("我对花生过敏，今后给饮食建议都考虑这个", {"memory_write"}, None),
    ]
    for message, kinds, transition in cases:
        result = await router.route(
            message=message,
            images=[],
            conversation_context=context,
            context_hints=AgentContextHints(
                timezone="Asia/Shanghai", occurred_at=datetime.now(UTC)
            ),
        )
        record("classification", request=message, plan=result.model_dump(mode="json"))
        assert result.tasks[0].task_type in kinds, "Inspect semantic classification evidence"
        if transition:
            assert result.tasks[0].task_update.transition == transition
        if transition == "new":
            assert not any(
                k in result.tasks[0].task_update.parameters for k in ("weight_kg", "sets", "reps")
            )


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_distinguishes_meal_reference_correction_and_consultation():
    entry_id, confirmation_id = str(uuid4()), str(uuid4())
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    active = AgentTask(
        task_type="nutrition_record_draft",
        status="completed",
        entities={"entry_id": entry_id, "confirmation_id": confirmation_id},
        parameters={"date": today, "meal_type": "lunch", "carbs_g": 60},
    )
    context = AgentConversationContext(
        task_state=AgentTaskState(active_task=active).model_dump(mode="json"),
        meal_confirmations=(
            {
                "entry_id": entry_id,
                "confirmation_id": confirmation_id,
                "operation_type": "nutrition_entry_create",
                "status": "succeeded",
                "meal_type": "lunch",
                "date": today,
            },
        ),
    )
    router = AgentIntentRouter(build_intent_router_model(get_settings()))
    cases = [
        ("晚饭照午饭记，不过鸡肉换成鱼", "nutrition_record_draft", "new"),
        ("昨天午饭也吃了同样的一份，补记一下", "nutrition_record_draft", "new"),
        ("刚才午饭的虾仁滑蛋其实是炒空心菜，改原记录", "nutrition_entry_update_draft", None),
        ("脂肪也偏高了，我实际吃得不油，重新估一下这顿", "nutrition_entry_update_draft", None),
        ("米饭不是200克，刚才那份改成150克", "nutrition_entry_update_draft", None),
        ("先别改，只解释一下这顿饭为什么脂肪偏高", "structured_data_query", None),
        ("我想看这顿午饭的具体记录，而不是每天总量", "structured_data_query", None),
    ]
    for message, kind, transition in cases:
        result = await router.route(
            message=message,
            images=[],
            conversation_context=context,
            context_hints=AgentContextHints(
                timezone="Asia/Shanghai", occurred_at=datetime.now(UTC)
            ),
        )
        record("meal_classification", request=message, plan=result.model_dump(mode="json"))
        task = result.tasks[0]
        assert task.task_type == kind, "Inspect semantic meal classification evidence"
        if transition:
            assert task.task_update.transition == transition
            assert task.task_update.entities == {}
            assert task.task_update.reference_entities.get("entry_id") == entry_id
