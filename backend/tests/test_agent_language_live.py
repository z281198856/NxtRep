"""Opt-in semantic routing evaluation; never writes business data."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from test_agent_task_state import meal_state

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.providers.models import (
    build_fallback_intent_router_model,
    build_intent_router_model,
)
from nxtrep_backend.schemas.agent import AgentContextHints
from nxtrep_backend.services.conversation import AgentConversationContext

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1", reason="Opt-in configured real model"
)


@pytest.mark.asyncio(loop_scope="session")
async def test_real_model_understands_existing_business_requests():
    settings = get_settings()
    router = AgentIntentRouter(
        build_intent_router_model(settings), build_fallback_intent_router_model(settings),
    )
    state = meal_state()
    state.active_task.missing_fields = ["selection"]
    meal = AgentConversationContext(task_state=state.model_dump(mode="json"))
    workout = AgentConversationContext(task_state={"active_task": {
        "task_type": "workout_record_draft", "status": "completed",
        "parameters": {"exercise_name": "卧推", "weight_kg": "60", "sets": 4, "reps": 8},
        "entities": {"workout_id": str(uuid4()), "workout_exercise_id": str(uuid4())},
    }})
    cases = [
        ("看看前天饮食多少热量", {"structured_data_query"}, None),
        ("10月10日的训练做了多少组", {"structured_data_query"}, None),
        ("上个月饮食热量平均多少", {"structured_data_query"}, None),
        ("热量目标应该是2200千卡", {"nutrition_target_draft"}, None),
        ("蛋白质目标应该调到120g", {"nutrition_target_draft"}, None),
        ("鸡腿饭多少热量", {"general_question"}, None),
        ("身高填错了，是175不是170", {"profile_update_draft"}, None),
        ("今天体重72.5公斤，帮我记一下", {"body_measurement_draft"}, None),
        ("今天卧推60kg，4组每组8次，记一下", {"workout_record_draft"}, None),
        ("不对，重量是55kg", {"workout_record_update_draft"}, workout),
        ("刚才那条卧推不要了", {"workout_record_void_draft"}, workout),
        ("新增一个自定义食品：无糖酸奶，每100g有60千卡", {"food_catalog_draft"}, None),
        ("我对花生过敏，以后推荐吃的时注意", {"memory_write"}, None),
        ("把明天的训练挪到后天", {"schedule_change_draft"}, None),
        ("这个鸡胸肉多少热量？", {"structured_data_query"}, meal),
        ("如果把第二个删掉会怎样？", {"general_question", "structured_data_query"}, meal),
        ("别改这个，先告诉我多少热量", {"general_question", "structured_data_query"}, meal),
        ("无需把11号的饮食改成10号", {"general_question", "structured_data_query"}, None),
        ("11号的饮食改到10号，再看看那天训练", {
            "nutrition_entry_update_draft", "structured_data_query",
        }, None),
        ("帮我制定训练计划，再看看上周训练量", {
            "training_plan_draft", "structured_data_query",
        }, None),
        ("帮我制定训练计划，别忘了把身高改成175", {
            "training_plan_draft", "profile_update_draft",
        }, None),
        ("力量训练后为什么需要补充蛋白质？", {"knowledge_retrieval"}, None),
    ]
    evidence = []
    path = Path(__file__).resolve().parents[2] / ".local" / "agent-language-live.json"
    limiter = asyncio.Semaphore(2)

    async def evaluate(message, expected, context):
        async with limiter:
            started = asyncio.get_running_loop().time()
            row = {"message": message, "expected": sorted(expected)}
            try:
                plan = await router.route(
                    message=message, images=[], conversation_context=context,
                    context_hints=AgentContextHints(
                        timezone="Asia/Shanghai", occurred_at=datetime.now(UTC),
                    ),
                )
                kinds = {task.task_type for task in plan.tasks}
                read_alternatives = expected <= {"general_question", "structured_data_query"}
                row.update(
                    plan=plan.model_dump(mode="json"),
                    passed=bool(kinds & expected) and kinds <= expected
                    if read_alternatives else kinds == expected,
                )
            except Exception as error:
                row.update(passed=False, error_type=type(error).__name__)
            row["elapsed_seconds"] = round(asyncio.get_running_loop().time() - started, 2)
            evidence.append(row)
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: row[k] for k in ("message", "passed", "elapsed_seconds")},
                             ensure_ascii=False), flush=True)

    await asyncio.gather(*(evaluate(*case) for case in cases))
    failures = [{"message": row["message"], "tasks": [
        t["task_type"] for t in row.get("plan", {}).get("tasks", [])
    ], "error_type": row.get("error_type")} for row in evidence if not row["passed"]]
    assert not failures, json.dumps(failures, ensure_ascii=False)
