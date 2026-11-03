"""Regression cases for saved-meal focus changes between conversation turns."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_agent_multiturn_pipeline import card, make_planner, tool_context

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentIntentPlan, AgentIntentTask
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState, AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.conversation import AgentConversationContext, ConversationService


def meal_state(entry_id, *, food_name=None, version=1):
    parameters = {"amount_g": "200"}
    if food_name:
        parameters["food_name"] = food_name
    return AgentTaskState(
        active_task=AgentTask(
            task_type="nutrition_entry_update_draft",
            status="ready",
            entities={"entry_id": str(entry_id), "item_index": 0, "version": version},
            parameters=parameters,
        )
    )


def branch_input(context, state):
    active = state.active_task
    return AgentBranchInput(
        user_id=context.user_id,
        message="改成200克",
        images=(),
        task=AgentIntentTask(
            task_type=active.task_type,
            task_id=active.task_id,
            confidence="high",
            routing_reason="继续修改已绑定餐食",
            task_update=AgentTaskUpdate(entities=active.entities, parameters=active.parameters),
        ),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )


def registered_meal_tools(monkeypatch, selected):
    read = AsyncMock(return_value={"status": "available", "selected_entry": selected})
    proposal = AsyncMock(
        return_value={
            "status": "confirmation_required",
            "confirmation": confirmation_payload(card("nutrition_entry_update")),
        }
    )
    tools = [
        SimpleNamespace(name="read_saved_meal_for_change", ainvoke=read),
        SimpleNamespace(name="propose_saved_meal_update", ainvoke=proposal),
    ]
    monkeypatch.setattr(
        "nxtrep_backend.services.agent_handlers.task_action.build_tools",
        lambda *args, **kwargs: tools,
    )
    return read, proposal


@pytest.mark.asyncio
@pytest.mark.parametrize("food_name", ["鸡胸肉", None])
async def test_changed_food_or_unbound_revision_requires_selection_before_proposal(
    monkeypatch, food_name
):
    entry_id = uuid4()
    state = meal_state(entry_id, food_name=food_name)
    selected = {
        "entry_id": str(entry_id),
        "version": 2,
        "items": [{"item_index": 0, "name": "米饭", "amount_g": "150"}],
    }
    read, proposal = registered_meal_tools(monkeypatch, selected)
    context = tool_context()

    result = await TaskActionHandler(context).execute(branch_input(context, state))

    assert result.status == "needs_input"
    assert result.missing_fields == ["selection"]
    assert "重新选择" in result.result["task_answer"]
    assert not result.confirmation_cards
    assert not result.requires_confirmation
    read.assert_awaited_once_with({"entry_id": str(entry_id)})
    proposal.assert_not_awaited()


@pytest.mark.asyncio
async def test_matching_food_label_uses_fresh_revision_for_existing_meal_update(monkeypatch):
    entry_id = uuid4()
    state = meal_state(entry_id, food_name="鸡胸肉")
    selected = {
        "entry_id": str(entry_id),
        "version": 3,
        "items": [{"item_index": 0, "name": "鸡胸肉", "amount_g": "150"}],
    }
    read, proposal = registered_meal_tools(monkeypatch, selected)
    context = tool_context()

    result = await TaskActionHandler(context).execute(branch_input(context, state))

    assert result.status == "completed"
    assert result.requires_confirmation
    assert len(result.confirmation_cards) == 1
    read.assert_awaited_once_with({"entry_id": str(entry_id)})
    proposal.assert_awaited_once()
    arguments = proposal.await_args.args[0]
    assert arguments["entry_id"] == str(entry_id)
    assert arguments["request"]["expected_version"] == 3
    assert arguments["request"]["changes"] == [{"item_index": 0, "amount_g": "200"}]


@pytest.mark.asyncio
async def test_approved_remove_retires_focus_before_same_index_is_reused():
    entry_id, confirmation_id = uuid4(), uuid4()
    state = meal_state(entry_id, food_name="鸡胸肉")
    state.active_task.entities["confirmation_id"] = str(confirmation_id)
    state.active_task.status = "awaiting_confirmation"
    executed_card = SimpleNamespace(
        id=confirmation_id,
        status="succeeded",
        operation_type="nutrition_entry_update",
        after={
            "entry_id": str(entry_id),
            "expected_version": 1,
            "remove_item_indices": [0],
        },
        result={"resource_id": str(entry_id), "resource_version": 2},
    )
    entry = SimpleNamespace(
        id=entry_id,
        version=2,
        meal_type="lunch",
        items=[{"name": "米饭", "amount_g": "150"}],
    )
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[executed_card, entry]))
    service = ConversationService(SimpleNamespace(session=session))
    conversation = SimpleNamespace(
        id=uuid4(), user_id=uuid4(), task_state=state.model_dump(mode="json")
    )

    hydrated = TaskStateManager.load(await service._current_task_state(conversation)).active_task

    assert hydrated.entities["entry_id"] == str(entry_id)
    assert hydrated.entities["version"] == 2
    assert "item_index" not in hydrated.entities
    assert "food_name" not in hydrated.parameters
    assert "amount_g" not in hydrated.parameters
    assert hydrated.missing_fields == ["selection"]
    assert hydrated.current_step == "clarify_target"
    assert [candidate.label for candidate in hydrated.candidates] == ["整顿午饭", "米饭"]
    assert session.scalar.await_count == 2


@pytest.mark.asyncio
async def test_second_candidate_after_model_clarification_binds_exact_entry():
    first_entry, second_entry = str(uuid4()), str(uuid4())
    state = TaskStateManager.apply_plan({}, "nutrition_entry_delete_draft")
    state = TaskStateManager.commit_results(
        state,
        [
            {
                "status": "needs_review",
                "candidates": [
                    {"entry_id": first_entry, "meal_type": "lunch"},
                    {"entry_id": second_entry, "meal_type": "dinner"},
                ],
            }
        ],
    )
    router = SimpleNamespace(route=AsyncMock(return_value=AgentIntentPlan(tasks=[AgentIntentTask(
        task_type="nutrition_entry_delete_draft", confidence="high", routing_reason="目标有歧义",
        missing_fields=["selection"],
    )])))
    planner, user_id = make_planner(router), uuid4()

    clarification = await planner.plan(
        user_id=user_id,
        request=AgentChatRequest(message="把刚才那个删了"),
        conversation_context=AgentConversationContext(task_state=state.model_dump(mode="json")),
    )
    assert clarification.intent_plan.tasks[0].missing_fields == ["selection"]
    assert TaskStateManager.load(
        clarification.conversation_context.task_state
    ).active_task.task_id == (state.active_task.task_id)

    chosen = await planner.plan(
        user_id=user_id,
        request=AgentChatRequest(message="第二个"),
        conversation_context=clarification.conversation_context,
    )

    task = chosen.intent_plan.tasks[0]
    assert task.task_type == "nutrition_entry_delete_draft"
    assert task.task_update.entities["entry_id"] == second_entry
    assert task.task_update.entities["entry_id"] != first_entry
    assert "item_index" not in task.task_update.entities
    assert "selection" not in task.missing_fields
    assert task.task_id == state.active_task.task_id
    router.route.assert_awaited_once()
    assert len(router.semantic_calls) == 2
