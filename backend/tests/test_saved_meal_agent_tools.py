from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from nxtrep_backend.agents.runtime import build_agent
from nxtrep_backend.agents.tools import AgentToolContext, groups_for_task
from nxtrep_backend.agents.tools.nutrition_changes import build_saved_meal_change_tools
from nxtrep_backend.core.config import Settings
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.nutrition import NutritionSavedEntryRevisionRequest


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"item_index": -1, "amount_g": 100}],
        [{"item_index": 0, "amount_g": 0}],
        [{"item_index": 0, "amount_g": None}],
        [{"item_index": 0, "amount_g": 100}, {"item_index": 0, "amount_g": 200}],
        [{"item_index": 0, "amount_g": 100, "name": "不允许改名"}],
    ],
)
def test_saved_meal_changes_require_valid_unique_indices_and_positive_grams(changes):
    with pytest.raises(ValidationError):
        NutritionSavedEntryRevisionRequest(changes=changes, expected_version=1, reason="更正")


@pytest.mark.parametrize(
    "task_type,permitted",
    [
        ("nutrition_entry_update_draft", "propose_saved_meal_update"),
        ("nutrition_entry_delete_draft", "propose_saved_meal_delete"),
    ],
)
def test_saved_meal_runtime_exposes_only_requested_action(task_type, permitted, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "nxtrep_backend.agents.runtime.create_agent", lambda **kwargs: captured.update(kwargs)
    )
    task = AgentIntentTask(task_type=task_type, confidence="high", routing_reason="test")
    build_agent(
        Settings(),
        tool_context=MagicMock(spec=AgentToolContext),
        model=MagicMock(),
        tool_groups=groups_for_task(task),
        task_type=task.task_type,
    )
    names = {t.name for t in captured["tools"]}
    expected = {permitted}
    if task_type == "nutrition_entry_delete_draft":
        expected.add("propose_saved_meal_item_remove")
    else:
        expected.add("propose_saved_meals_date_change")
    assert {n for n in names if n.startswith("propose_")} == expected
    assert "save_memory" not in names and "read_saved_meal_for_change" in names


def context(count=1, duplicate_food=False):
    entries = [
        SimpleNamespace(
            id=uuid4(),
            version=1,
            meal_type="lunch",
            eaten_at=datetime.now(UTC),
            items=[{"name": "米饭", "amount_g": "200"}],
            totals={"kcal": "260"},
            notes=None,
        )
        for _ in range(count)
    ]
    if duplicate_food:
        entries[0].items.append({"name": "米饭", "amount_g": "100"})
    service = SimpleNamespace(
        list_entries=AsyncMock(return_value=entries),
        get_saved_entry=AsyncMock(return_value=entries[0]),
        propose_saved_entry_change=AsyncMock(return_value=object()),
        create_entry_delete_confirmation=AsyncMock(return_value=object()),
    )
    return SimpleNamespace(user_id=uuid4(), nutrition_service=service), entries[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("delete", [False, True])
async def test_saved_meal_requires_read_and_same_request_reuses_one_card(delete, monkeypatch):
    ctx, entry = context()
    monkeypatch.setattr(
        "nxtrep_backend.agents.tools.nutrition_changes.confirmation_payload",
        lambda _: {"operation_type": "test"},
    )
    tools = {t.name: t for t in build_saved_meal_change_tools(ctx)}
    propose = tools["propose_saved_meal_delete" if delete else "propose_saved_meal_update"]
    request = {"expected_version": 1, "reason": "更正"}
    if not delete:
        request["changes"] = [{"item_index": 0, "amount_g": 100}]
    args = {"entry_id": str(entry.id), "request": request}
    assert (await propose.ainvoke(args))["status"] == "needs_review"
    found = await tools["read_saved_meal_for_change"].ainvoke(
        {"entry_id": str(entry.id), "food_name": "米饭"}
    )
    assert found["status"] == "available" and found["selected_entry"]["matching_item_indices"] == [
        0
    ]
    a, b = await propose.ainvoke(args), await propose.ainvoke(args)
    assert a == b and a["status"] == "confirmation_required"
    service = ctx.nutrition_service
    assert (
        service.create_entry_delete_confirmation if delete else service.propose_saved_entry_change
    ).await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("count,duplicate_food", [(2, False), (1, True)])
async def test_multiple_meals_or_duplicate_foods_require_choice(count, duplicate_food):
    ctx, entry = context(count, duplicate_food)
    tools = {tool.name: tool for tool in build_saved_meal_change_tools(ctx)}
    read, propose = tools["read_saved_meal_for_change"], tools["propose_saved_meal_update"]
    day = entry.eaten_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    found = await read.ainvoke({"day": day, "food_name": "米饭"})
    assert found["status"] == "needs_review"
    assert (await read.ainvoke({}))["status"] == "needs_review"
    assert (
        await propose.ainvoke(
            {
                "entry_id": str(entry.id),
                "request": {
                    "expected_version": 1,
                    "changes": [{"item_index": 0, "amount_g": 100}],
                    "reason": "更正",
                },
            }
        )
    )["status"] == "needs_review"
    ctx.nutrition_service.propose_saved_entry_change.assert_not_awaited()
