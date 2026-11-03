"""Pending meal quantity edits reuse the authoritative confirmation and existing tools."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.task_action import TaskActionHandler


def pending_card():
    return SimpleNamespace(
        id=uuid4(),
        operation_type="nutrition_entry_create",
        status="pending",
        before=None,
        after={
            "entry": {"notes": "按常见份量估算，用油量不确定"},
            "preview": {
                "items": [
                    {"name": "番茄炒蛋", "amount_g": "250"},
                    {"name": "清炒西兰花", "amount_g": "200"},
                    {"name": "熟白米饭", "amount_g": "200"},
                ]
            },
        },
        impact="确认后生效",
        version=4,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def setup_action(card, *, amount=200, changed=None, transition="correct"):
    confirmation = MagicMock(get=AsyncMock(return_value=card))
    nutrition = MagicMock(propose_entry=AsyncMock(), revise_pending_entry=AsyncMock())
    ctx = AgentToolContext(
        user_id=uuid4(),
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=MagicMock(),
        workout_service=MagicMock(),
        nutrition_service=nutrition,
        body_service=MagicMock(),
        confirmation_service=confirmation,
        memory_service=MagicMock(),
    )
    task = AgentIntentTask(
        task_type="nutrition_record_draft",
        confidence="high",
        routing_reason="明确修改同一份草稿",
        task_id=uuid4(),
        task_update=AgentTaskUpdate(
            transition=transition,
            entities={"confirmation_id": str(card.id), "item_index": 0},
            parameters={
                "food_name": "米饭",
                "amount_g": amount,
                "_changed_fields": changed if changed is not None else ["food_name", "amount_g"],
            },
        ),
    )

    async def run(message):
        return await TaskActionHandler(ctx).execute(
            AgentBranchInput(user_id=ctx.user_id, task=task, message=message, images=())
        )

    return run, ctx, task


@pytest.mark.asyncio
async def test_equal_portion_returns_original_card_without_any_new_draft():
    old = pending_card()
    run, ctx, _ = setup_action(old)
    result = await run("米饭改成200克，番茄炒蛋和西兰花不变")
    assert result.status == "completed"
    assert str(result.confirmation_cards[0].confirmation_id) == str(old.id)
    assert "已经按200克计算" in result.result["task_answer"]
    assert "草稿" not in result.result["task_answer"]
    assert result.requires_confirmation
    ctx.nutrition_service.propose_entry.assert_not_called()
    ctx.nutrition_service.revise_pending_entry.assert_not_called()
    assert [item["tool_name"] for item in ctx.tool_runs] == ["read_confirmation_status"]


@pytest.mark.asyncio
async def test_changed_portion_uses_live_card_version_and_real_food_index_only():
    old = pending_card()
    run, ctx, _ = setup_action(old, amount=250)
    revised = pending_card()
    revised.after["replaces_confirmation_id"] = str(old.id)
    revised.after["preview"]["items"][2]["amount_g"] = "250"
    ctx.nutrition_service.revise_pending_entry.return_value = revised
    result = await run("把米饭的份量改成250克，其他不变")
    assert result.status == "completed"
    assert result.confirmation_cards[0].confirmation_id == revised.id
    args = ctx.nutrition_service.revise_pending_entry.call_args.args
    assert args[:2] == (ctx.user_id, old.id)
    revision = args[2]
    assert revision.expected_version == 4
    assert [(item.item_index, item.amount_g) for item in revision.changes] == [(2, 250)]
    assert revision.notes is None  # Preserve the original estimation assumptions.
    ctx.nutrition_service.propose_entry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "改成200克",
        "番茄炒蛋和米饭改成200克",
        "米饭不要改成200克",
        "不是让你把米饭改成200克",
        "米饭的蛋白质改成200克",
    ],
)
async def test_ambiguous_target_asks_instead_of_reusing_stale_item_index(message):
    run, ctx, _ = setup_action(pending_card())
    result = await run(message)
    assert result.status == "needs_input"
    assert result.missing_fields == ["selection"]
    assert "哪项食物" in result.result["task_answer"]
    ctx.nutrition_service.revise_pending_entry.assert_not_called()
    ctx.nutrition_service.propose_entry.assert_not_called()


@pytest.mark.asyncio
async def test_preview_recipe_note_does_not_hide_the_explicit_food_name():
    old = pending_card()
    old.after["preview"]["items"][0]["name"] = "番茄炒蛋（家常，含油）"
    run, ctx, _ = setup_action(old, amount=250)
    result = await run("把刚才的番茄炒蛋份量改成250克")
    assert result.confirmation_cards[0].confirmation_id == old.id
    ctx.nutrition_service.revise_pending_entry.assert_not_called()


@pytest.mark.asyncio
async def test_conflicting_preservation_of_selected_food_requires_clarification():
    run, ctx, _ = setup_action(pending_card(), amount=250)
    result = await run("米饭改成250克，米饭不变")
    assert result.status == "needs_input"
    assert "同时要求修改和保留" in result.result["task_answer"]
    ctx.nutrition_service.revise_pending_entry.assert_not_called()
    ctx.nutrition_service.propose_entry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "cancelled", "rejected", "expired", "failed"])
async def test_closed_card_never_becomes_an_independent_new_meal(status):
    old = pending_card()
    old.status = status
    run, ctx, _ = setup_action(old, amount=250)
    result = await run("米饭改成250克")
    assert result.status == "needs_input"
    assert "已不在有效待确认状态" in result.result["task_answer"]
    ctx.nutrition_service.revise_pending_entry.assert_not_called()
    ctx.nutrition_service.propose_entry.assert_not_called()


@pytest.mark.asyncio
async def test_expired_timestamp_is_not_presented_as_an_active_noop_card():
    old = pending_card()
    old.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    run, ctx, _ = setup_action(old)
    result = await run("米饭改成200克")
    assert result.status == "needs_input"
    assert not result.confirmation_cards
    ctx.nutrition_service.revise_pending_entry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,changed,transition",
    [
        ("米饭改成250克，西兰花改成300克", ["food_name", "amount_g"], "correct"),
        ("米饭改成250克，午饭改成晚饭", ["food_name", "amount_g"], "correct"),
        ("米饭改成250克，日期改成昨天", ["food_name", "amount_g", "eaten_at"], "correct"),
        ("米饭改成250克", ["food_name", "amount_g"], "new"),
    ],
)
async def test_complex_edits_or_new_tasks_remain_with_existing_scoped_planner(
    message, changed, transition
):
    run, ctx, _ = setup_action(pending_card(), amount=250, changed=changed, transition=transition)
    assert await run(message) is None
    ctx.confirmation_service.get.assert_not_called()
    ctx.nutrition_service.revise_pending_entry.assert_not_called()


@pytest.mark.asyncio
async def test_router_items_shape_or_stale_grams_cannot_override_explicit_current_grams():
    old = pending_card()
    run, ctx, task = setup_action(old, amount=999, changed=["items"])
    task.task_update.parameters["items"] = [{"food_name": "米饭", "amount_g": 200}]
    result = await run("米饭改成200克，其他不变")
    assert result.status == "completed"
    assert result.confirmation_cards[0].confirmation_id == old.id
    ctx.nutrition_service.revise_pending_entry.assert_not_called()


@pytest.mark.asyncio
async def test_tool_timeout_reaches_existing_error_handler_without_retry_or_success():
    run, ctx, _ = setup_action(pending_card(), amount=250)
    ctx.nutrition_service.revise_pending_entry.side_effect = TimeoutError("synthetic timeout")
    with pytest.raises(TimeoutError):
        await run("米饭改成250克")
    ctx.nutrition_service.revise_pending_entry.assert_awaited_once()
    ctx.nutrition_service.propose_entry.assert_not_called()
