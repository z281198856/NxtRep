"""Opt-in real-model acceptance on a disposable account and already-running API.

Run this file with RUN_LIVE_AGENT_TESTS=1 and RUN_MULTITURN_LIVE_TESTS=1, -x.
It starts no service and records no authentication material. Stop at the first
failure and inspect the local evidence before spending more model requests.
"""

import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import (
    AgentConversation,
    AgentMessage,
    AgentRun,
    Exercise,
    Workout,
    WorkoutSet,
)
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_MULTITURN_LIVE_TESTS") != "1",
    reason="Opt-in only: real model and a running local API",
)
EVIDENCE = ROOT / ".local" / "agent-multiturn-live-20261008.json"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def remove_private_acceptance_exercises(live_account):  # noqa: F811
    _, user_id, _, _, _ = live_account
    try:
        yield
    finally:
        # Cleanup only this disposable account's two possible fallback exercises.
        # Do not rely on installed foreign-key behavior or touch public catalog rows.
        async with SessionFactory() as session:
            await session.execute(
                delete(Exercise).where(
                    Exercise.owner_user_id == user_id,
                    Exercise.name_zh.in_(["多轮验收杠铃卧推", "多轮验收上斜杠铃卧推"]),
                )
            )
            await session.commit()


class LiveTurns:
    def __init__(self, client, conversation_id, evidence):
        self.client, self.conversation_id, self.evidence = client, conversation_id, evidence
        self.last_body = None

    def record(self, scenario, **data):
        self.evidence.append({"scenario": scenario, **data})
        EVIDENCE.parent.mkdir(exist_ok=True)
        EVIDENCE.write_text(
            json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def chat(self, message, *, status):
        body = {
            "message": message,
            "conversation_id": self.conversation_id,
            "client_turn_id": str(uuid4()),
            "context_hints": {
                "timezone": "Asia/Shanghai",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        }
        self.last_body = body
        response = await self.client.post("/agent/chat", json=body)
        payload = response.json()
        self.record(message, http_status=response.status_code, response=payload)
        async with SessionFactory() as session:
            conversation = await session.get(AgentConversation, UUID(self.conversation_id))
            self.record("task_state", state=conversation.task_state)
        assert response.status_code == 200, "Inspect local multi-turn acceptance evidence"
        assert payload["status"] == status, "Inspect local multi-turn acceptance evidence"
        text = payload["message"]
        assert re.search(r"[\u3400-\u9fff]", text)
        assert not any(
            marker in text
            for marker in (
                "retrieved_at",
                "query_time",
                "tool_call_id",
                "回答：",
                "分析：",
            )
        ), "User-facing reply must not expose internal labels or search metadata"
        assert not re.search(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", text)
        return payload

    async def approve(self, card):
        response = await self.client.post(
            f"/confirmations/{card['confirmation_id']}/approve",
            json={"expected_version": card["version"]},
            headers={"Idempotency-Key": str(uuid4())},
        )
        payload = response.json()
        self.record("批准草稿", http_status=response.status_code, result=payload)
        assert response.status_code == 200, "Inspect local multi-turn acceptance evidence"
        assert payload["status"] == "succeeded"
        return payload

    async def replay(self, original):
        async with SessionFactory() as session:
            filters = AgentMessage.conversation_id == UUID(self.conversation_id)
            before = await session.scalar(
                select(func.count()).select_from(AgentMessage).where(filters)
            )
            run_before = await session.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.conversation_id == UUID(self.conversation_id))
            )
        response = await self.client.post("/agent/chat", json=self.last_body)
        payload = response.json()
        self.record("同一请求标识重放", response=payload)
        assert response.status_code == 200 and payload["run_id"] == original["run_id"]
        assert payload["confirmation_cards"] == original["confirmation_cards"]
        async with self.client.stream(
            "POST",
            f"/agent/conversations/{self.conversation_id}/messages",
            params={"granularity": "chunk"},
            json={key: value for key, value in self.last_body.items() if key != "conversation_id"},
        ) as stream:
            assert stream.status_code == 200
            events = [
                json.loads(line[5:].strip())
                async for line in stream.aiter_lines()
                if line.startswith("data:")
            ]
        self.record("同一请求标识 SSE 重放", events=events)
        assert any(
            event.get("event") == "run_started" and event.get("run_id") == original["run_id"]
            for event in events
        )
        assert any(
            event.get("event") == "completed"
            and event.get("response", {}).get("run_id") == original["run_id"]
            for event in events
        )
        async with SessionFactory() as session:
            after = await session.scalar(
                select(func.count()).select_from(AgentMessage).where(filters)
            )
            run_after = await session.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.conversation_id == UUID(self.conversation_id))
            )
        assert after == before and run_after == run_before


def card_of(payload, operation):
    cards = payload["confirmation_cards"]
    assert len(cards) == 1 and cards[0]["operation_type"] == operation
    return cards[0]


async def exact_exercise(client, name):
    response = await client.get("/exercises", params={"keyword": name, "page_size": 100})
    assert response.status_code == 200
    exact = [item for item in response.json()["list"] if item["name_zh"] == name]
    if len(exact) == 1:
        return name
    # A unique private name avoids ambiguity with an installed public exercise catalog.
    private_name = "多轮验收" + name
    response = await client.post(
        "/exercises",
        json={
            "name_zh": private_name,
            "equipment": "barbell",
            "primary_muscles": ["chest"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return private_name


async def workout_values(user_id, workout_id=None):
    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Workout).where(Workout.user_id == user_id)
        )
        sets = (
            []
            if workout_id is None
            else list(
                await session.scalars(
                    select(WorkoutSet)
                    .where(
                        WorkoutSet.workout_id == UUID(workout_id), WorkoutSet.voided_at.is_(None)
                    )
                    .order_by(WorkoutSet.set_index)
                )
            )
        )
        return count, [{"weight_kg": str(item.weight_kg), "reps": item.reps} for item in sets]


@pytest.mark.asyncio(loop_scope="session")
async def test_real_multiturn_collection_switch_correction_references_and_replay(live_account):  # noqa: F811
    client, user_id, _, _, _ = live_account
    evidence = []
    created = await client.post("/agent/conversations", json={"title": "生产多轮训练验收"})
    assert created.status_code == 201
    workout = LiveTurns(client, created.json()["id"], evidence)
    bench = await exact_exercise(client, "杠铃卧推")
    incline = await exact_exercise(client, "上斜杠铃卧推")
    baseline_workouts, _ = await workout_values(user_id)
    initial = await workout.chat(f"帮我记录今天{bench}。", status="needs_input")
    assert not initial["confirmation_cards"]
    weight = await workout.chat("60kg。", status="needs_input")
    assert not weight["confirmation_cards"]
    ready = await workout.chat("四组，每组8个。", status="completed")
    original = card_of(ready, "workout_record_create")
    request = original["after"]["request"]
    assert Decimal(request["weight_kg"]) == 60 and request["sets"] == 4 and request["reps"] == 8
    assert (await workout_values(user_id))[0] == baseline_workouts
    await workout.replay(ready)
    question = await workout.chat(
        "对了，一份鸡腿饭大概多少热量？只要一般估算。", status="completed"
    )
    assert not question["confirmation_cards"]
    resumed = await workout.chat("继续刚才的训练。", status="completed")
    assert not resumed["confirmation_cards"] or [
        card["confirmation_id"] for card in resumed["confirmation_cards"]
    ] == [original["confirmation_id"]]
    restored = await client.get(f"/agent/conversations/{workout.conversation_id}/confirmations")
    assert restored.status_code == 200
    assert [card["confirmation_id"] for card in restored.json()["confirmation_cards"]] == [
        original["confirmation_id"]
    ]
    approved = await workout.approve(original)
    workout_id = approved["result"]["resource_id"]
    count, sets = await workout_values(user_id, workout_id)
    assert count == baseline_workouts + 1 and len(sets) == 4
    correction = await workout.chat("不对，重量是55kg。", status="completed")
    changed = card_of(correction, "workout_record_update")
    assert changed["after"]["workout_id"] == workout_id
    assert Decimal(changed["after"]["request"]["weight_kg"]) == 55
    await workout.approve(changed)
    count, sets = await workout_values(user_id, workout_id)
    assert count == baseline_workouts + 1 and all(
        Decimal(item["weight_kg"]) == 55 and item["reps"] == 8 for item in sets
    )
    added = await workout.chat(f"再加一个{incline}。", status="needs_input")
    assert not added["confirmation_cards"]
    async with SessionFactory() as session:
        state = (await session.get(AgentConversation, UUID(workout.conversation_id))).task_state
    assert {"weight_kg", "sets", "reps"} <= set(state["active_task"]["missing_fields"])
    assert not ({"weight_kg", "sets", "reps"} & state["active_task"]["parameters"].keys())
    cancelled = await workout.chat("算了，不记了。", status="completed")
    assert not cancelled["confirmation_cards"]
    assert (await workout_values(user_id))[0] == baseline_workouts + 1

    for name, values in (
        ("米饭", {"kcal": 130, "protein_g": 3, "carbs_g": 28, "fat_g": 1}),
        ("鸡胸肉", {"kcal": 165, "protein_g": 31, "carbs_g": 0, "fat_g": 3.6}),
    ):
        response = await client.post(
            "/foods",
            json={"name": name, "basis_amount_g": 100, **values},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 201
    created = await client.post("/agent/conversations", json={"title": "生产多轮餐食验收"})
    assert created.status_code == 201
    meal = LiveTurns(client, created.json()["id"], evidence)
    draft = await meal.chat("午饭记录米饭200g、鸡胸肉150g。", status="completed")
    meal_card = card_of(draft, "nutrition_entry_create")
    saved = await meal.approve(meal_card)
    entry_id = saved["result"]["resource_id"]
    revised = await meal.chat("刚才那个鸡胸肉改成200g。", status="completed")
    revision_card = card_of(revised, "nutrition_entry_update")
    assert revision_card["after"]["entry_id"] == entry_id
    assert Decimal(revision_card["after"]["changes"][0]["amount_g"]) == 200
    await meal.approve(revision_card)
    ambiguous = await meal.chat("把刚才那个删了。", status="needs_input")
    assert not ambiguous["confirmation_cards"]
    removed = await meal.chat("只删除午饭中的鸡胸肉，保留米饭和整顿午饭。", status="completed")
    removal_card = card_of(removed, "nutrition_entry_update")
    assert removal_card["after"]["entry_id"] == entry_id
    assert len(removal_card["after"]["remove_item_indices"]) == 1
    await meal.approve(removal_card)
    entry = await client.get(f"/nutrition/entries/{entry_id}")
    assert entry.status_code == 200
    assert len(entry.json()["items"]) == 1 and "米饭" in entry.json()["items"][0]["name"]
    assert Decimal(entry.json()["items"][0]["amount_g"]) == 200
    meal.record("餐内单项删除验收完成", entry=entry.json())
