"""Natural requests must retain their meaning across deterministic shortcuts."""

from dataclasses import replace
from uuid import uuid4

import pytest
from test_agent_intent_router import make_dependencies, meal_context
from test_agent_task_state import meal_state

from nxtrep_backend.agents.intent_router import AgentIntentRouter, meal_nutrient_follow_up_task
from nxtrep_backend.schemas.agent import AgentIntentPlan
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,tasks",
    [
        ("看看前天饮食多少热量", ["structured_data_query"]),
        ("10月10日的训练做了多少组", ["structured_data_query"]),
        ("上个月饮食热量平均多少", ["structured_data_query"]),
        ("热量目标应该是2200千卡", ["nutrition_target_draft"]),
        ("蛋白质目标应该调到120g", ["nutrition_target_draft"]),
        ("那个训练重量应该是55kg", ["workout_record_update_draft"]),
        ("鸡腿饭多少热量", ["general_question"]),
        ("这个动作怎么练", ["general_question"]),
        ("无需把11号的饮食改成10号", ["general_question"]),
        ("不用把11号的午饭挪到10号", ["general_question"]),
        ("11号的饮食改到10号，再看看那天训练", [
            "nutrition_entry_update_draft", "structured_data_query",
        ]),
        ("先把11号饮食改到10号，再删除重复晚饭", [
            "nutrition_entry_update_draft", "nutrition_entry_delete_draft",
        ]),
        ("帮我制定训练计划，再看看上周训练量", [
            "training_plan_draft", "structured_data_query",
        ]),
        ("帮我制定训练计划，别忘了把身高改成175", [
            "training_plan_draft", "profile_update_draft",
        ]),
        ("这个草稿保存了吗，再看一下昨天午饭", ["structured_data_query"]),
    ],
)
async def test_ambiguous_personal_or_compound_requests_reach_semantic_router(message, tasks):
    model, structured = make_dependencies()
    expected = AgentIntentPlan(tasks=[{
        "task_type": kind, "confidence": "high", "routing_reason": "语义计划保留实际对象",
    } for kind in tasks])
    structured.ainvoke.return_value = {"parsed": expected}
    result = await AgentIntentRouter(model).route(message=message, images=[])
    structured.ainvoke.assert_awaited_once()
    assert result == expected


@pytest.mark.parametrize(
    "message",
    [
        "这个鸡胸肉多少热量？",
        "如果把第二个删掉会怎样？",
        "别改这个，先告诉我多少热量",
        "这个动作怎么练",
        "把鸡胸肉改成200g，再查一下训练记录",
        "刚才那个鸡胸肉改成200g，其他不变，再查一下训练记录",
        "这个是之前的记录吗",
        "不是55kg",
        "不是4组",
        "不是8次",
    ],
)
def test_question_negation_or_new_task_does_not_select_or_modify_pending_target(message):
    state = meal_state()
    state.active_task.missing_fields = ["selection"]
    state.active_task.parameters["amount_g"] = "180"
    before = state.model_dump(mode="json")
    result = TaskStateManager.prepare_turn(state, message)
    assert result.selection is None
    assert result.parameters == {} and result.entities == {}
    assert not result.handled and not result.clarification_required
    assert result.state.model_dump(mode="json") == before


def test_unique_stale_meal_candidate_does_not_capture_unrelated_reference():
    state = meal_state()
    state.active_task.candidates = [state.active_task.candidates[-1]]
    state.active_task.missing_fields = ["selection"]
    result = TaskStateManager.prepare_turn(state, "这个动作怎么练")
    assert result.selection is None
    assert result.state == state


def test_unique_meal_candidate_cannot_supply_an_unmatched_food_identity():
    state = meal_state()
    state.active_task.candidates = [state.active_task.candidates[-1]]
    result = TaskStateManager.prepare_turn(state, "刚才那个鸡腿肉改成200g")
    assert result.selection is None
    assert result.entities == {} and result.parameters == {}
    assert result.clarification_required


@pytest.mark.parametrize("message", ["那个", "把刚才那个删除了", "这个删掉了"])
def test_unique_explicit_selection_or_removal_still_resolves_actual_id(message):
    state = meal_state()
    state.active_task.candidates = [state.active_task.candidates[-1]]
    result = TaskStateManager.prepare_turn(state, message)
    assert result.selection == state.active_task.candidates[0]
    assert result.entities["entry_id"] == state.active_task.entities["entry_id"]


@pytest.mark.parametrize("operation", ["nutrition_entries_date_change", "nutrition_entry_delete"])
def test_date_or_delete_card_is_not_a_new_meal_to_reestimate(operation):
    confirmation_id = str(uuid4())
    context = replace(
        meal_context(),
        task_state={"active_task": {
            "task_type": "nutrition_entry_update_draft",
            "status": "awaiting_confirmation",
            "parameters": {"action": "change_date"},
            "entities": {"confirmation_id": confirmation_id},
        }},
        meal_confirmations=({
            "confirmation_id": confirmation_id,
            "operation_type": operation,
            "status": "pending",
        },),
    )
    assert meal_nutrient_follow_up_task("脂肪偏高，重新估一下", context) is None


@pytest.mark.parametrize("message", [
    "脂肪偏高，再看看昨天训练",
    "不用调整脂肪，先看热量",
])
def test_meal_feedback_does_not_override_a_second_request_or_negation(message):
    assert meal_nutrient_follow_up_task(message, meal_context()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "力量训练后为什么需要补充蛋白质？",
    "如何安排力量训练的恢复时间？",
    "请解释如何制定一份力量训练计划？",
])
async def test_conceptual_knowledge_uses_semantic_model(message):
    model, structured = make_dependencies()
    from test_agent_intent_router import supply_plan

    supply_plan(structured, "knowledge_retrieval")
    result = await AgentIntentRouter(model).route(
        message=message, images=[], conversation_context=AgentConversationContext(),
    )
    assert result.tasks[0].task_type == "knowledge_retrieval"
    structured.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_named_meals_are_moved_together_without_moving_breakfast():
    from test_meal_date_change import meal, setup

    pipeline, service, _, meals = setup("day")
    breakfast = meal("breakfast", 0)
    service.list_entries.return_value = [breakfast, *meals]
    result = await pipeline.turn("十一号午饭和晚饭改到十号")
    assert result["execution_bundle"].branch_results[0].requires_confirmation
    body = service.propose_saved_date_change.call_args.args[1]
    assert {e.entry_id for e in body.entries} == {m.id for m in meals}


@pytest.mark.asyncio
async def test_missing_one_named_meal_does_not_silently_move_only_the_other():
    from test_meal_date_change import setup

    pipeline, service, _, meals = setup("day")
    service.list_entries.return_value = [meals[0]]
    result = await pipeline.turn("十一号午饭和晚饭改到十号")
    branch = result["execution_bundle"].branch_results[0]
    assert branch.status == "needs_input"
    assert "晚饭" in branch.result["task_answer"]
    service.propose_saved_date_change.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("meal_types", [[{}], ["invalid"], [], "lunch"])
async def test_invalid_multi_meal_scope_clarifies_without_execution(meal_types):
    from test_meal_date_change import setup

    pipeline, service, router, _ = setup("meals")
    router.route.return_value.tasks[0].task_update.parameters["meal_types"] = meal_types
    result = await pipeline.turn("十一号的一部分饮食改到十号")
    branch = result["execution_bundle"].branch_results[0]
    assert branch.status == "needs_input"
    service.propose_saved_date_change.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_recovery_keeps_current_question_and_does_not_restart_historical_write():
    import json
    from dataclasses import replace

    from langchain_core.messages import AIMessage, ToolMessage
    from test_general_question_branch_handler import make_handler, make_input, make_react_agent

    from nxtrep_backend.services.conversation import ConversationMessageContext

    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [AIMessage(content="还需要读取具体记录。")]},
        {"messages": [ToolMessage(
            name="read_nutrition_entries", tool_call_id="read",
            content=json.dumps({"status": "available", "entries": []}),
        ), AIMessage(content="请说明你要查询哪一餐的米饭。")]},
    ]
    request = replace(
        make_input(task_type="structured_data_query", required_context=["nutrition"]),
        message="这个米饭多少热量？",
        conversation_context=AgentConversationContext(recent_messages=(
            ConversationMessageContext(role="user", content="把11号的一餐饮食改到10号"),
            ConversationMessageContext(role="assistant", content="是哪一餐？"),
        )),
    )
    result = await make_handler(agent).execute(request)
    assert result.status == "completed"
    assert agent.ainvoke.await_count == 2
    retry = agent.ainvoke.call_args.args[0]["messages"][-1]
    recovery = json.loads(retry["content"])
    assert recovery["current_user_message"] == request.message
    assert recovery["query_recovery"]["missing_domains"] == ["nutrition"]
    assert not result.confirmation_cards


@pytest.mark.parametrize("status,message,expected", [
    ("pending", "这个米饭多少热量？", "2026-10-11"),
    ("succeeded", "这个米饭多少热量？", "2026-10-10"),
    ("cancelled", "这个米饭多少热量？", "2026-10-11"),
    ("pending", "今天这个米饭多少热量？", None),
    ("pending", "10月9日这餐多少热量？", None),
    ("pending", "鸡腿饭多少热量？", None),
])
def test_meal_reference_date_tracks_business_confirmation_but_not_explicit_user_date(
    status, message, expected,
):
    from test_general_question_branch_handler import make_input

    from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler

    confirmation_id = str(uuid4())
    request = replace(
        make_input(task_type="structured_data_query", required_context=["nutrition"]),
        message=message,
        conversation_context=AgentConversationContext(
            task_state={"suspended_task": {
                "task_type": "nutrition_entry_update_draft", "status": "collecting",
                "parameters": {"action": "change_date", "source_date": "2026-10-11"},
                "entities": {"confirmation_id": confirmation_id},
            }},
            meal_confirmations=({
                "confirmation_id": confirmation_id, "status": status,
                "source_date": "2026-10-11", "target_date": "2026-10-10",
            },),
        ),
    )
    day = GeneralQuestionBranchHandler._meal_query_day(request)
    assert (day.isoformat() if day else None) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("with_confirmation,requested_confirmation", [
    (False, False), (True, True), (False, True),
])
async def test_specific_meal_query_reads_saved_date_through_existing_owned_tool(
    with_confirmation, requested_confirmation,
):
    from datetime import UTC, date, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from langchain_core.messages import AIMessage, ToolMessage
    from test_agent_multiturn_pipeline import card, tool_context
    from test_general_question_branch_handler import make_input, make_react_agent

    from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler

    service = SimpleNamespace(list_entries=AsyncMock(return_value=[SimpleNamespace(
        id=uuid4(), version=1, meal_type="lunch", eaten_at=datetime(2026, 10, 11, 4, tzinfo=UTC),
        items=[{"name": "米饭", "amount_g": "200"}], totals={"kcal": "260"},
        is_flexible_meal=False, notes=None,
    )]))
    selected_id = str(service.list_entries.return_value[0].id)
    confirmation = card("nutrition_entries_date_change", {"request": {
        "source_date": "2026-10-11", "target_date": "2026-10-10",
    }})
    confirmation_service = SimpleNamespace(get=AsyncMock(return_value=confirmation))
    context = tool_context(nutrition_service=service, confirmation_service=confirmation_service)
    agent = make_react_agent({})
    agent.ainvoke.side_effect = lambda payload, **_: {
        "messages": [*payload["messages"], AIMessage(content="这份米饭200克，共260千卡。")],
    }
    request = replace(
        make_input(task_type="structured_data_query", required_context=["nutrition"] + (
            ["confirmation"] if requested_confirmation else []
        )),
        user_id=context.user_id, message="这个米饭多少热量？",
        conversation_context=AgentConversationContext(task_state={"suspended_task": {
            "task_type": "nutrition_entry_update_draft", "status": "collecting",
            "parameters": {"action": "change_date", "source_date": "2026-10-11"},
            "entities": {"entry_id": selected_id, **(
                {"confirmation_id": str(confirmation.id)} if with_confirmation else {}
            )},
        }}),
    )
    handler = GeneralQuestionBranchHandler(lambda _: agent, tool_context=context)
    with patch(
        "nxtrep_backend.services.agent_handlers.general.load_personal_context",
        AsyncMock(return_value={}),
    ):
        result = await handler.execute(request)
    service.list_entries.assert_awaited_once_with(
        user_id=context.user_id, day=date(2026, 10, 11), meal_type=None,
    )
    assert agent.ainvoke.await_count == 1
    assert result.status == "completed" and "260" in result.result["answer"]
    assert not result.confirmation_cards
    assert any(run["tool_name"] == "read_nutrition_entries" for run in result.tool_runs)
    assert confirmation_service.get.await_count == int(with_confirmation)
    read_message = next(
        item for item in agent.ainvoke.call_args.args[0]["messages"]
        if isinstance(item, ToolMessage) and item.name == "read_nutrition_entries"
    )
    import json

    evidence = json.loads(read_message.content)
    assert evidence["scope_entry_id"] == selected_id
    assert [e["id"] for e in evidence["entries"]] == [selected_id]
