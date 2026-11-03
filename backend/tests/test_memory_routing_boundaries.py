from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask


def task(kind, instructions=()):
    return AgentIntentTask(
        task_type=kind,
        confidence="high",
        routing_reason="semantic routing",
        memory_instructions=list(instructions),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,correct_type",
    [
        ("帮我在食品库添加自定义食品双层吉士汉堡", "food_catalog_draft"),
        ("把午餐米饭改成100克", "nutrition_record_draft"),
        ("把明天的训练改到后天", "schedule_change_draft"),
        ("帮我记录今天体重64公斤", "body_measurement_draft"),
        ("把每日热量目标改成2000千卡", "nutrition_target_draft"),
        ("把训练记录中的深蹲重量改成50公斤", "general_question"),
    ],
)
async def test_memory_review_reclassifies_business_operations_before_writes(message, correct_type):
    model = MagicMock(spec=BaseChatModel)
    structured = model.with_structured_output.return_value
    structured.ainvoke = AsyncMock(
        side_effect=[
            {"parsed": AgentIntentPlan(tasks=[task("memory_write")])},
            {"parsed": AgentIntentPlan(tasks=[task(correct_type)])},
        ]
    )
    result = await AgentIntentRouter(model).route(message=message, images=[])
    assert [t.task_type for t in result.tasks] == [correct_type]
    assert structured.ainvoke.await_count == 2
    prompt = structured.ainvoke.await_args.args[0][0].content
    assert "允许主动形成记忆" in prompt and "业务操作误分类" in prompt


@pytest.mark.asyncio
async def test_mixed_operation_keeps_only_grounded_stable_fact_in_memory_scope():
    message = "把酸奶加入食品库，我乳糖不耐受"
    fact = {
        "action": "save",
        "category": "exercise_limit",
        "content": "乳糖不耐受",
        "evidence": "我乳糖不耐受",
    }
    model = MagicMock(spec=BaseChatModel)
    structured = model.with_structured_output.return_value
    structured.ainvoke = AsyncMock(
        side_effect=[
            {"parsed": AgentIntentPlan(tasks=[task("memory_write")])},
            {
                "parsed": AgentIntentPlan(
                    tasks=[task("food_catalog_draft"), task("memory_write", [fact])]
                )
            },
        ]
    )
    result = await AgentIntentRouter(model).route(message=message, images=[])
    assert [t.task_type for t in result.tasks] == ["food_catalog_draft", "memory_write"]
    assert result.tasks[1].memory_instructions[0].content == "乳糖不耐受"


@pytest.mark.parametrize(
    "instructions",
    [
        [],
        [
            {
                "action": "save",
                "category": "allergy",
                "content": "花生过敏",
                "evidence": "我花生过敏",
            }
        ],
    ],
)
def test_ungrounded_or_missing_memory_evidence_removes_write_capability(instructions):
    result = AgentIntentRouter._ground_memory_instructions(
        AgentIntentPlan(tasks=[task("memory_write", instructions)]),
        "今天午饭吃鸡胗",
    )
    assert result.tasks[0].task_type == "general_question"
    assert result.tasks[0].memory_instructions == []


def test_food_tasks_merge_without_losing_other_intents_or_creating_each_food_twice():
    plan = AgentIntentPlan(
        tasks=[task("food_catalog_draft"), task("memory_write"), task("food_catalog_draft")]
    )
    result = AgentIntentRouter._merge_food_catalog_tasks(plan)
    assert [item.task_type for item in result.tasks] == ["food_catalog_draft", "memory_write"]
