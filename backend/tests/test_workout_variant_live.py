"""Real repeated App wording, with disposable account and no device account switch."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.db.models import AgentRun, Workout, WorkoutSet
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1", reason="Opt-in real model"
)


@pytest.mark.asyncio(loop_scope="session")
async def test_repeated_smith_incline_request_never_becomes_free_barbell(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    events = []
    conversation_id = None

    async def chat(message):
        nonlocal conversation_id
        response = await client.post(
            "/agent/chat",
            json={
                "message": message,
                "conversation_id": conversation_id,
                "client_turn_id": str(uuid4()),
                "context_hints": {"occurred_at": datetime.now(UTC).isoformat()},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        conversation_id = payload["conversation_id"]
        async with SessionFactory() as session:
            run = await session.get(AgentRun, UUID(payload["run_id"]))
            events.append({"request": message, "response": payload, "trace": run.checkpoint})
        (ROOT / ".local/workout-variant-live.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    first = await chat("今天杠铃卧推55kg4组每组8次，帮我记录。")
    assert len(first["confirmation_cards"]) == 1
    card = first["confirmation_cards"][0]
    approved = await client.post(
        f"/confirmations/{card['confirmation_id']}/approve",
        json={
            "expected_version": card["version"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert approved.status_code == 200
    async with SessionFactory() as session:
        before = await session.scalar(
            select(func.count())
            .select_from(WorkoutSet)
            .join(Workout)
            .where(
                Workout.user_id == user_id,
            )
        )
    for _ in range(2):
        response = await chat("还练了史密斯上斜推胸30kg4乘12")
        for candidate in response["confirmation_cards"]:
            request = candidate["after"]["request"]
            assert request["exercise_name"] == "史密斯上斜推胸"
            assert request["exercise_id"] != card["after"]["request"]["exercise_id"]
            assert (
                float(request["weight_kg"]) == 30 and request["sets"] == 4 and request["reps"] == 12
            )
    restored = await client.get(f"/agent/conversations/{conversation_id}/confirmations")
    assert restored.status_code == 200
    pending = restored.json()["confirmation_cards"]
    assert len(pending) == 1
    assert pending[0]["after"]["preview"]["exercise_name"] == "史密斯上斜推胸"
    assert pending[0]["message_sequence"] in {4, 6}
    assert restored.json()["completed_cards"][0]["message_sequence"] == 2
    async with SessionFactory() as session:
        after = await session.scalar(
            select(func.count())
            .select_from(WorkoutSet)
            .join(Workout)
            .where(
                Workout.user_id == user_id,
            )
        )
    assert after == before
