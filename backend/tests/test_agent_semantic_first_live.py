"""Opt-in semantic planning/runtime acceptance; only disposable business data."""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentConversation, AgentRun, NutritionEntry, Workout
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1",
    reason="Opt-in real model/API acceptance with disposable accounts",
)
EVIDENCE = ROOT / ".local/semantic-first-live.json"


async def chat(client, message, conversation_id=None):
    response = await client.post("/agent/chat", json={
        "message": message, "conversation_id": conversation_id, "client_turn_id": str(uuid4()),
        "context_hints": {
            "timezone": "Asia/Shanghai", "occurred_at": datetime.now(UTC).isoformat(),
        },
    })
    payload = response.json()
    event = {"request": message, "http_status": response.status_code, "response": payload}
    if response.status_code == 200:
        async with SessionFactory() as session:
            run = await session.get(AgentRun, UUID(payload["run_id"]))
            conversation = await session.get(AgentConversation, UUID(payload["conversation_id"]))
            event.update(task_state=conversation.task_state, plan=run.checkpoint.get("action_plan"),
                         tools=run.checkpoint.get("tool_runs"))
    events = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    events.append(event)
    EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    assert response.status_code == 200, "Inspect semantic-first-live.json"
    assert payload["status"] != "failed", "Inspect semantic-first-live.json"
    return payload, event


def workout_request(payload):
    cards = [c for c in payload["confirmation_cards"]
             if c["operation_type"] == "workout_record_create"]
    assert len(cards) == 1
    return cards[0]["after"]["request"]


@pytest.mark.asyncio(loop_scope="session")
async def test_short_exercise_name_can_be_resolved_in_same_turn(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    async with SessionFactory() as session:
        before = await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        ))
    response, event = await chat(client, "卧推55kg4组每组8次")
    assert event["plan"]["tasks"][0]["task_type"] == "workout_record_draft"
    assert response["status"] == "completed", "Expected a reviewable draft; inspect live evidence"
    body = workout_request(response)
    assert Decimal(body["weight_kg"]) == 55 and body["sets"] == 4 and body["reps"] == 8
    assert body["exercise_id"] == "10000000-0000-4000-8000-000000000002"
    task = event["task_state"]["active_task"]
    assert task["entities"]["exercise_id"] == body["exercise_id"]
    assert task["parameters"]["exercise_name"] == "杠铃卧推"
    assert any(b.get("result", {}).get("semantic_resolution") == "resolved"
               for b in response["analysis_results"])
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Workout).where(
            Workout.user_id == user_id,
        )) == before


@pytest.mark.asyncio(loop_scope="session")
async def test_slots_query_interruption_resume_and_cancel_all_use_model(live_account):  # noqa: F811
    client, *_ = live_account
    start, event = await chat(client, "帮我记录今天的杠铃卧推。")
    conversation_id = start["conversation_id"]
    task_id = event["task_state"]["active_task"]["task_id"]
    assert start["status"] == "needs_input" and not start["confirmation_cards"]
    for message in ("55kg", "四组"):
        response, event = await chat(client, message, conversation_id)
        assert response["status"] == "needs_input" and not response["confirmation_cards"]
        assert event["task_state"]["active_task"]["task_id"] == task_id
        assert "确定性延续" not in event["plan"]["tasks"][0]["routing_reason"]
    query, event = await chat(client, "先查今天已记录的热量，先别记训练。", conversation_id)
    assert query["status"] == "completed" and not query["confirmation_cards"]
    assert event["plan"]["tasks"][0]["task_type"] == "structured_data_query"
    assert event["task_state"]["suspended_task"]["task_id"] == task_id
    _, event = await chat(client, "继续刚才的训练。", conversation_id)
    assert event["task_state"]["active_task"]["task_id"] == task_id
    response, event = await chat(client, "8个", conversation_id)
    assert response["status"] == "completed"
    body = workout_request(response)
    assert Decimal(body["weight_kg"]) == 55 and body["sets"] == 4 and body["reps"] == 8
    assert event["task_state"]["active_task"]["task_id"] == task_id
    cancelled, event = await chat(client, "算了，这份草稿不要了。", conversation_id)
    assert cancelled["status"] == "completed"
    assert event["plan"]["tasks"][0]["task_type"] == "confirmation_cancel"
    assert any(r.get("status") == "cancelled" for b in cancelled["analysis_results"]
               for r in (b.get("result") or {}).get("task_tool_results", []))


@pytest.mark.asyncio(loop_scope="session")
async def test_meal_target_correction_then_query_does_not_approve_or_duplicate(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    async with SessionFactory() as session:
        repo = SqlAlchemyConfirmationRepository(session)
        service = NutritionService(SqlAlchemyNutritionRepository(session), repo)
        card = await service.propose_entry(user_id=user_id, body=NutritionEntryCreateRequest(
            meal_type="lunch", eaten_at=datetime.now(UTC), items=[{
                "name": name, "amount_g": grams, "basis_amount_g": 100,
                "kcal": 120, "protein_g": 15, "carbs_g": 10, "fat_g": 2,
                "source": "model_estimated", "confidence": "low",
            } for name, grams in (("米饭", 200), ("鸡胸肉", 150))],
        ))
        await DatabaseConfirmationService(repo).approve(user_id, card.id, card.version)
        entry_id = UUID(card.result["resource_id"])
        await session.commit()
    edit, _ = await chat(client, "把今天午饭里的鸡胸肉改成200克，保留米饭。")
    assert edit["status"] == "completed" and len(edit["confirmation_cards"]) == 1
    card = edit["confirmation_cards"][0]
    assert card["operation_type"] == "nutrition_entry_update"
    assert card["after"]["entry_id"] == str(entry_id)
    assert card["after"]["changes"] == [{"item_index": 1, "amount_g": "200"}]
    query, event = await chat(
        client, "先不要改，查一下这顿午饭现在的热量和蛋白质。", edit["conversation_id"],
    )
    assert query["status"] == "completed" and not query["confirmation_cards"]
    assert all(t["task_type"] in {"structured_data_query", "general_question"}
               for t in event["plan"]["tasks"])
    async with SessionFactory() as session:
        entry = await session.get(NutritionEntry, entry_id)
        assert Decimal(entry.items[0]["amount_g"]) == 200
        assert Decimal(entry.items[1]["amount_g"]) == 150
        assert await session.scalar(select(func.count()).select_from(NutritionEntry).where(
            NutritionEntry.user_id == user_id, NutritionEntry.meal_type == "lunch",
        )) == 1
