from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_saved_meal_agent_tools import context

from nxtrep_backend.agents.tools.nutrition_changes import build_saved_meal_change_tools
from nxtrep_backend.schemas.nutrition import NutritionSavedEntryRevisionRequest


@pytest.mark.parametrize(
    "body",
    [
        {"remove_item_indices": [-1]},
        {"remove_item_indices": [0, 0]},
        {"remove_item_indices": [0], "changes": [{"item_index": 0, "amount_g": 100}]},
        {"remove_item_indices": []},
    ],
)
def test_remove_item_request_requires_valid_nonoverlapping_changes(body):
    with pytest.raises(ValidationError):
        NutritionSavedEntryRevisionRequest(expected_version=1, reason="移除误记食物", **body)


def test_remove_item_request_accepts_removal_only_and_legacy_changes():
    body = NutritionSavedEntryRevisionRequest(
        expected_version=1, reason="移除误记食物", remove_item_indices=[1]
    )
    assert body.changes == []
    old = NutritionSavedEntryRevisionRequest(
        expected_version=1, reason="更正份量", changes=[{"item_index": 0, "amount_g": 150}]
    )
    assert old.remove_item_indices == []


@pytest.mark.asyncio
async def test_remove_item_tool_requires_read_version_and_reuses_one_proposal(monkeypatch):
    ctx, entry = context()
    ctx.nutrition_service.propose_saved_entry_change = AsyncMock(return_value=object())
    monkeypatch.setattr(
        "nxtrep_backend.agents.tools.nutrition_changes.confirmation_payload",
        lambda _: {"operation_type": "nutrition_entry_update"},
    )
    tools = {tool.name: tool for tool in build_saved_meal_change_tools(ctx)}
    remove = tools["propose_saved_meal_item_remove"]
    args = {"entry_id": str(entry.id), "item_index": 0, "expected_version": 1, "reason": "误记"}
    assert (await remove.ainvoke(args))["status"] == "needs_review"
    ctx.nutrition_service.propose_saved_entry_change.assert_not_awaited()
    await tools["read_saved_meal_for_change"].ainvoke({"entry_id": str(entry.id)})
    assert (await remove.ainvoke({**args, "expected_version": 2}))["status"] == "needs_review"
    a, b = await remove.ainvoke(args), await remove.ainvoke(args)
    assert a == b and a["status"] == "confirmation_required"
    ctx.nutrition_service.propose_saved_entry_change.assert_awaited_once()
    body = ctx.nutrition_service.propose_saved_entry_change.await_args.args[2]
    assert body.remove_item_indices == [0] and body.changes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("item_index", -1), ("expected_version", 0), ("reason", "")]
)
async def test_remove_item_tool_rejects_bad_arguments_before_service(field, value):
    ctx, entry = context()
    remove = next(
        tool
        for tool in build_saved_meal_change_tools(ctx)
        if tool.name == "propose_saved_meal_item_remove"
    )
    with pytest.raises(ValidationError):
        await remove.ainvoke(
            {
                "entry_id": str(entry.id),
                "item_index": 0,
                "expected_version": 1,
                "reason": "误记",
                field: value,
            }
        )
    ctx.nutrition_service.propose_saved_entry_change.assert_not_awaited()
