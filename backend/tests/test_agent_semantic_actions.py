"""Semantic routing, reference/target isolation, and bounded plan repair."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from nxtrep_backend.agents.intent_router import AgentIntentRouter, AgentIntentRoutingError
from nxtrep_backend.agents.tools.registry import _scope_preflight
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentContextHints,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState, AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext


def meal_context():
    entry_id = str(uuid4())
    active = AgentTask(
        task_type="nutrition_record_draft",
        status="completed",
        entities={"entry_id": entry_id},
        parameters={"meal_type": "lunch", "date": "2026-10-14", "carbs_g": 60},
    )
    return AgentConversationContext(
        task_state=AgentTaskState(
            active_task=active,
        ).model_dump(mode="json")
    ), entry_id


def plan(kind, **update):
    return AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type=kind,
                confidence="high",
                routing_reason="语义规划测试",
                task_update=AgentTaskUpdate(**update),
            )
        ]
    )


def router_with(*plans):
    model = MagicMock(spec=BaseChatModel)
    structured = MagicMock(
        ainvoke=AsyncMock(
            side_effect=[{"parsed": p, "raw": None, "parsing_error": None} for p in plans]
        )
    )
    model.with_structured_output.return_value = structured
    return AgentIntentRouter(model), structured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "晚饭是把虾仁滑蛋换成了炒空心菜，其他一样",
        "晚餐照午饭记，只是鸡肉换成鱼，没称重",
        "昨天晚上也吃了同样的一份，帮我记上",
        "先别改午饭，我问的是晚饭能不能照这样搭配",
        "刚才午餐的鸡蛋实际换成青菜了，改原记录",
        "今天怎么练？",
        "训练后为什么需要蛋白质？",
        "这个草稿保存了吗？",
        "碳水约六十克",
        "十一号的饮食记错了应该是十号的",
    ],
)
async def test_business_and_knowledge_inputs_reach_semantic_model(message):
    context, _ = meal_context()
    expected = plan("general_question", transition="new")
    router, structured = router_with(expected)
    assert await router.route(message=message, images=[], conversation_context=context) == expected
    structured.ainvoke.assert_awaited_once()
    payload = json.loads(structured.ainvoke.await_args.args[0][1].content)
    assert payload["message"] == message
    assert payload["conversation_context"]["task_state"]["active_task"]


@pytest.mark.asyncio
async def test_scope_conflict_is_replanned_without_forcing_a_new_or_old_meal():
    context, entry_id = meal_context()
    wrong = plan(
        "nutrition_entry_update_draft",
        transition="correct",
        entities={"entry_id": entry_id},
        parameters={"meal_type": "dinner"},
    )
    corrected = plan(
        "nutrition_record_draft",
        transition="new",
        reference_entities={"entry_id": entry_id},
        parameters={"meal_type": "dinner"},
    )
    router, structured = router_with(wrong, corrected)
    result = await router.route(
        message="晚饭和午饭一样，只是换一道菜", images=[], conversation_context=context
    )
    assert result == corrected
    assert structured.ainvoke.await_count == 2
    review = json.loads(structured.ainvoke.await_args.args[0][1].content)
    assert review["validation_conflicts"][0]["code"] == "MEAL_TARGET_SCOPE_CONFLICT"


@pytest.mark.asyncio
async def test_repeated_conflicting_plan_stops_after_one_semantic_repair():
    context, entry_id = meal_context()
    wrong = plan("nutrition_record_draft", transition="new", entities={"entry_id": entry_id})
    router, structured = router_with(wrong, wrong)
    with pytest.raises(AgentIntentRoutingError, match="冲突"):
        await router.route(message="再记一餐", images=[], conversation_context=context)
    assert structured.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_new_meal_has_a_reference_but_no_old_write_target_or_nutrient_goal():
    context, entry_id = meal_context()
    router, _ = router_with(
        plan(
            "nutrition_record_draft",
            transition="new",
            reference_entities={"entry_id": entry_id},
            parameters={
                "meal_type": "dinner",
                "replace_item": {
                    "from_food_name": "虾仁滑蛋",
                    "to_food_name": "炒空心菜",
                },
            },
        )
    )
    assembler = MagicMock(load_memories=AsyncMock(return_value=()))
    result = await AgentRequestPlanner(
        resolver=MagicMock(), intent_router=router, context_assembler=assembler
    ).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="晚饭换青菜，其他和午饭一样"),
        conversation_context=context,
    )
    task = result.intent_plan.tasks[0]
    assert task.task_update.entities == {}
    assert task.task_update.reference_entities == {"entry_id": entry_id}
    assert "carbs_g" not in task.task_update.parameters
    assert "amount_g" not in task.missing_fields
    assert task.task_id != context.task_state["active_task"]["task_id"]


@pytest.mark.asyncio
async def test_invented_reference_id_is_removed_before_state_and_execution():
    context, _ = meal_context()
    invented = str(uuid4())
    router, _ = router_with(
        plan(
            "nutrition_record_draft",
            transition="new",
            reference_entities={"entry_id": invented},
            parameters={"food_name": "米饭"},
        )
    )
    result = await AgentRequestPlanner(
        resolver=MagicMock(),
        intent_router=router,
        context_assembler=MagicMock(load_memories=AsyncMock(return_value=())),
    ).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="另外记一份米饭"),
        conversation_context=context,
    )
    assert result.intent_plan.tasks[0].task_update.reference_entities == {}


def test_reference_scope_does_not_authorize_mutating_the_source():
    source, different = str(uuid4()), str(uuid4())
    scope = {"_reference_entities": {"entry_id": source}}
    assert (
        _scope_preflight(
            "propose_nutrition_entry_from_reference", {"source_entry_id": source}, scope
        )
        is None
    )
    conflict = _scope_preflight(
        "propose_nutrition_entry_from_reference", {"source_entry_id": different}, scope
    )
    assert conflict["error_code"] == "REFERENCE_ENTITY_CONFLICT"
    assert (
        _scope_preflight(
            "propose_nutrition_entry_from_reference",
            {"source_entry_id": source},
            {"entry_id": source},
        )["error_code"]
        == "MEAL_REVISION_REQUIRED"
    )


def test_reference_persists_across_parameter_completion_without_becoming_a_target():
    context, entry_id = meal_context()
    initial = TaskStateManager.apply_plan(
        context.task_state,
        "nutrition_record_draft",
        AgentTaskUpdate(
            transition="new",
            reference_entities={"entry_id": entry_id},
            parameters={"meal_type": "dinner"},
        ),
    )
    continued = TaskStateManager.apply_plan(
        initial,
        "nutrition_record_draft",
        AgentTaskUpdate(transition="continue", parameters={"note": "少油"}),
    )
    assert continued.active_task.reference_entities == {"entry_id": entry_id}
    assert continued.active_task.entities == {}


@pytest.mark.asyncio
async def test_food_date_does_not_become_a_missing_training_date():
    wrong = plan("nutrition_record_draft", transition="new", missing_fields=["workout_date"])
    correct = plan(
        "nutrition_record_draft",
        transition="new",
        parameters={"date": "2026-10-13", "meal_type": "dinner"},
    )
    router, structured = router_with(wrong, correct)
    result = await router.route(
        message="昨天晚饭也这样吃的，帮我记上",
        images=[],
        context_hints=AgentContextHints(
            timezone="Asia/Shanghai", occurred_at=datetime(2026, 10, 14, 12, tzinfo=UTC)
        ),
    )
    assert result == correct and structured.ainvoke.await_count == 2
    request = json.loads(structured.ainvoke.await_args.args[0][1].content)["request"]
    assert request["local_calendar"]["yesterday"] == "2026-10-13"


@pytest.mark.asyncio
async def test_food_replacement_with_grams_is_not_silently_executed_as_a_portion_change():
    task = plan(
        "nutrition_entry_update_draft",
        transition="correct",
        parameters={"amount_g": 200, "replacement": {"food_name": "空心菜"}},
    ).tasks[0]
    result = await TaskActionHandler(MagicMock()).execute(
        AgentBranchInput(
            user_id=uuid4(),
            message="鸡蛋换成200克空心菜",
            task=task,
            images=(),
        )
    )
    assert result is None, "The tool-enabled model must handle this operation"


@pytest.mark.asyncio
async def test_ambiguous_meal_edit_is_deferred_to_semantic_tool_resolution():
    task = plan(
        "nutrition_entry_update_draft", transition="correct", missing_fields=["selection"]
    ).tasks[0]
    task = task.model_copy(update={"missing_fields": ["selection"]})
    context = MagicMock()
    result = await TaskActionHandler(context).execute(
        AgentBranchInput(
            user_id=uuid4(),
            message="把那个换了",
            task=task,
            images=(),
        )
    )
    assert result is None
    assert not context.mock_calls
