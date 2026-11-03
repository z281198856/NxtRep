"""Real multi-turn boundaries for meal-local estimate corrections."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_agent_intent_router import make_dependencies
from test_agent_meal_focus_safety import branch_input, meal_state, tool_context
from test_agent_multiturn_pipeline import make_planner
from test_agent_semantic_first import planner as semantic_planner
from test_general_question_branch_handler import make_handler, make_input, make_react_agent

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentIntentPlan, AgentIntentTask
from nxtrep_backend.schemas.agent_task import (
    AgentTask,
    AgentTaskCandidate,
    AgentTaskState,
    AgentTaskUpdate,
)
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_nutrition_feedback import is_nutrition_estimate_feedback
from nxtrep_backend.services.agent_task_state import TaskStateManager, is_business_removal_request
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


def context_for_meal(*, saved=False, suspended=False):
    entities = {"confirmation_id": str(uuid4())}
    if saved:
        entities["entry_id"] = str(uuid4())
    task = AgentTask(
        task_type="nutrition_entry_update_draft" if saved else "nutrition_record_draft",
        status="completed" if saved else "awaiting_confirmation",
        entities=entities,
        parameters={"food_name": "米饭", "amount_g": 200},
    )
    state = AgentTaskState(suspended_task=task) if suspended else AgentTaskState(active_task=task)
    return task, AgentConversationContext(task_state=state.model_dump(mode="json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize(
    "feedback",
    ["脂肪也偏高了", "我觉得不是很油", "蛋白质估低了", "碳水偏高", "热量偏低", "脂肪调低一点"],
)
async def test_estimate_feedback_uses_bound_meal_without_old_chat_keywords(saved, feedback):
    task, context = context_for_meal(saved=saved)
    model, structured = make_dependencies()
    structured.ainvoke.return_value = {"parsed": AgentIntentPlan(tasks=[AgentIntentTask(
        task_type=task.task_type, confidence="high", routing_reason="纠正原餐估算",
        task_update=AgentTaskUpdate(transition="correct", entities=task.entities),
    )]), "raw": None, "parsing_error": None}
    result = await AgentIntentRouter(model).route(
        message=feedback, images=[], conversation_context=context
    )
    routed = result.tasks[0]
    assert routed.task_type == (
        "nutrition_entry_update_draft" if saved else "nutrition_record_draft"
    )
    assert routed.task_update.transition == "correct"
    assert routed.task_update.entities == task.entities
    assert not routed.missing_fields
    structured.ainvoke.assert_awaited_once()


@pytest.mark.parametrize(
    "text",
    [
        "为什么脂肪这么高",
        "每天脂肪目标调低",
        "脂肪偏高了但不要改",
        "推荐一些少油食物",
        "一份鸡腿多少热量",
        "记住以后少油",
        "不用改，只解释为什么",
    ],
)
def test_knowledge_goals_and_negation_are_not_estimate_feedback(text):
    assert not is_nutrition_estimate_feedback(text)


@pytest.mark.parametrize(
    "message",
    [
        "豆腐也改成150克，其他不变，先不要确认",
        "米饭改成150克，不要动鸡胸肉",
        "不要删除米饭",
        "别撤销刚才那条",
        "请不要把鸡胸肉删掉",
        "不要改鸡胸肉，只改米饭份量",
        "刚才那个先不要确认",
        "不要确认或保存，先给修改草稿",
        "don't delete that meal",
    ],
)
def test_deferred_approval_and_negated_actions_are_not_business_removal(message):
    assert not is_business_removal_request(message)


@pytest.mark.parametrize(
    "message",
    [
        "把刚才那个删了",
        "只删除鸡胸肉，保留米饭",
        "不要动米饭，只删除鸡胸肉",
        "刚才那个不要",
        "米饭不要了",
        "撤销刚才的记录",
    ],
)
def test_actual_removal_intent_is_retained(message):
    assert is_business_removal_request(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("known_name", [False, True])
@pytest.mark.parametrize(
    "message",
    ["豆腐也改成150克，其他不变，先不要确认", "豆腐实际是150克，其他不变"],
)
async def test_portion_change_with_deferred_approval_does_not_take_delete_shortcut(
    known_name, message
):
    original, context = context_for_meal(saved=True)
    entry_id = original.entities["entry_id"]
    original.entities["item_index"] = 2
    original.candidates = [
        AgentTaskCandidate(id=entry_id, kind="meal", label="整顿午饭"),
        AgentTaskCandidate(
            id=uuid4(),
            parent_id=entry_id,
            kind="meal_item",
            item_index=1,
            label="豆腐" if known_name else "虚构验收豆腐菜",
        ),
    ]
    context = replace(
        context, task_state=AgentTaskState(active_task=original).model_dump(mode="json")
    )
    prepared = TaskStateManager.prepare_turn(context.task_state, message)
    assert not prepared.clarification_required
    routed = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type="nutrition_entry_update_draft",
                confidence="high",
                routing_reason="只修订份量，暂不确认",
                task_update=AgentTaskUpdate(
                    transition="correct",
                    entities={**original.entities, "item_index": 1},
                    parameters={"food_name": "豆腐", "amount_g": 150},
                ),
            )
        ]
    )
    router = type("Router", (), {"route": AsyncMock(return_value=routed)})()
    planned = await semantic_planner(router).plan(
        user_id=uuid4(), request=AgentChatRequest(message=message), conversation_context=context
    )
    assert planned.intent_plan.tasks[0].task_type == "nutrition_entry_update_draft"
    assert planned.intent_plan.tasks[0].task_id == original.task_id
    assert not planned.intent_plan.tasks[0].missing_fields
    assert planned.intent_plan.tasks[0].task_update.entities.get("item_index") in (None, 1)
    assert planned.intent_plan.tasks[0].task_update.entities["entry_id"] == entry_id
    assert str(planned.intent_plan.tasks[0].task_update.parameters["amount_g"]) == "150"
    router.route.assert_awaited_once()


def test_pending_removal_preview_keeps_original_food_indices_in_state_candidates():
    original, context = context_for_meal(saved=True)
    entry_id = original.entities["entry_id"]
    state = TaskStateManager.commit_results(
        context.task_state,
        results=[
            {
                "status": "available",
                "selected_entry": {
                    "entry_id": entry_id,
                    "version": 1,
                    "items": [
                        {"name": "豆腐", "item_index": 1, "amount_g": "200"},
                        {"name": "米饭", "item_index": 2, "amount_g": "200"},
                    ],
                },
            }
        ],
    )
    prepared = TaskStateManager.prepare_turn(state, "豆腐改成150克")
    assert prepared.entities["item_index"] == 1
    assert prepared.entities["entry_id"] == entry_id
    assert not prepared.clarification_required


@pytest.mark.asyncio
async def test_read_detour_then_feedback_restores_same_task_and_does_not_require_new_grams():
    original, context = context_for_meal(suspended=True)
    routed = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type="nutrition_record_draft",
                confidence="high",
                routing_reason="重估",
                missing_fields=["amount_g"],
                task_update=AgentTaskUpdate(
                    transition="correct", entities=original.entities, missing_fields=["amount_g"]
                ),
            )
        ]
    )
    router = type("Router", (), {"route": AsyncMock(return_value=routed)})()
    planned = await make_planner(router).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="脂肪也偏高了，我觉得不是很油"),
        conversation_context=context,
    )
    result = planned.intent_plan.tasks[0]
    assert result.task_id == original.task_id
    assert result.task_update.entities["confirmation_id"] == original.entities["confirmation_id"]
    assert "amount_g" not in result.missing_fields
    assert TaskStateManager.load(planned.conversation_context.task_state).suspended_task is None


@pytest.mark.asyncio
async def test_active_pending_meal_is_not_redirected_to_another_saved_meal():
    original, context = context_for_meal()
    context = replace(
        context,
        meal_confirmations=(
            {
                "confirmation_id": str(uuid4()),
                "entry_id": str(uuid4()),
                "operation_type": "nutrition_entry_create",
                "status": "succeeded",
            },
        ),
    )
    model, structured = make_dependencies()
    structured.ainvoke.return_value = {"parsed": AgentIntentPlan(tasks=[AgentIntentTask(
        task_type="nutrition_record_draft", confidence="high", routing_reason="更正当前待确认餐食",
        task_update=AgentTaskUpdate(transition="correct", entities=original.entities),
    )]), "raw": None, "parsing_error": None}
    result = await AgentIntentRouter(model).route(
        message="脂肪偏高了", images=[], conversation_context=context
    )
    assert result.tasks[0].task_type == "nutrition_record_draft"
    assert result.tasks[0].task_update.entities == original.entities


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
async def test_meal_wide_feedback_drops_stale_rice_focus_and_calculated_gaps(saved):
    original, context = context_for_meal(saved=saved)
    original.entities["item_index"] = 2
    context = replace(
        context, task_state=AgentTaskState(active_task=original).model_dump(mode="json")
    )
    routed = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type=original.task_type,
                confidence="high",
                routing_reason="全餐估算纠正",
                task_update=AgentTaskUpdate(
                    transition="correct",
                    entities=original.entities,
                    missing_fields=["amount_g", "items[].fat_g", "kcal"],
                ),
            )
        ]
    )
    router = type("Router", (), {"route": AsyncMock(return_value=routed)})()
    planned = await make_planner(router).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="脂肪偏高了，实际不是很油"),
        conversation_context=context,
    )
    task = planned.intent_plan.tasks[0]
    assert task.task_id == original.task_id
    assert not task.missing_fields
    assert "item_index" not in task.task_update.entities
    assert "food_name" not in task.task_update.parameters
    assert "amount_g" not in task.task_update.parameters
    assert task.task_update.entities["confirmation_id"] == original.entities["confirmation_id"]


@pytest.mark.asyncio
async def test_multiple_meals_without_focus_require_selection():
    context = AgentConversationContext(
        recent_messages=(
            ConversationMessageContext(role="assistant", content="午餐饮食草稿待确认。"),
        ),
        meal_confirmations=tuple(
            {
                "confirmation_id": str(uuid4()),
                "operation_type": "nutrition_entry_create",
                "status": "pending",
            }
            for _ in range(2)
        ),
    )
    model, structured = make_dependencies()
    structured.ainvoke.return_value = {"parsed": AgentIntentPlan(tasks=[AgentIntentTask(
        task_type="nutrition_record_draft", confidence="high", routing_reason="存在多份餐食",
        missing_fields=["selection"],
    )]), "raw": None, "parsing_error": None}
    result = await AgentIntentRouter(model).route(
        message="脂肪偏高了", images=[], conversation_context=context
    )
    assert result.tasks[0].missing_fields == ["selection"]
    assert result.tasks[0].task_update is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["脂肪偏高了", "米饭200克，其他份量不变，脂肪调低一点", "脂肪改成20克", "我觉得不是很油"],
)
async def test_saved_reestimation_never_uses_stale_portion_shortcut(message):
    state = meal_state(uuid4(), food_name="米饭")
    context = tool_context()
    branch = replace(branch_input(context, state), message=message)
    assert await TaskActionHandler(context).execute(branch) is None
    assert not context.tool_runs


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "需要核对营养依据。"])
async def test_revision_business_error_keeps_real_reason_and_does_not_retry_create(content):
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    name="propose_nutrition_entry_revision",
                    tool_call_id="review",
                    content=json.dumps(
                        {
                            "status": "needs_review",
                            "error_code": "MEAL_REVISION_REVIEW_REQUIRED",
                            "message": "此项来自食品库，不能改成模型估算。",
                        }
                    ),
                ),
                AIMessage(content=content),
            ]
        }
    )
    task = make_input(task_type="nutrition_record_draft", required_context=[]).task.model_copy(
        update={
            "task_update": AgentTaskUpdate(
                transition="correct", entities={"confirmation_id": str(uuid4())}
            ),
        }
    )
    result = await make_handler(agent).execute(
        replace(
            make_input(task_type="nutrition_record_draft", required_context=[]),
            task=task,
            message="脂肪偏高了",
        )
    )
    assert result.status == "needs_input"
    assert "食品库" in result.result["answer"]
    assert not result.confirmation_cards
    agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_revision_retry_instructs_revision_tool_and_distinct_failure():
    agent = make_react_agent({"messages": [AIMessage(content="尚未完成估算。")]})
    task = make_input(task_type="nutrition_record_draft", required_context=[]).task.model_copy(
        update={
            "task_update": AgentTaskUpdate(
                transition="correct", entities={"confirmation_id": str(uuid4())}
            ),
        }
    )
    result = await make_handler(agent).execute(
        replace(
            make_input(task_type="nutrition_record_draft", required_context=[]),
            task=task,
            message="脂肪偏高了",
        )
    )
    assert result.status == "failed"
    assert result.error.code == "NUTRITION_ENTRY_REVISION_NOT_CREATED"
    assert agent.ainvoke.await_count == 2
    messages = agent.ainvoke.await_args.args[0]["messages"]
    assert any("propose_nutrition_entry_revision" in str(message) for message in messages)
    assert any(
        "不能新建独立餐食" in str(message) or "不要另建" in str(message) for message in messages
    )
