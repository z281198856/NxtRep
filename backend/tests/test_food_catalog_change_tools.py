from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.agents.runtime import build_agent
from nxtrep_backend.agents.tools import AgentToolContext, groups_for_task
from nxtrep_backend.agents.tools.nutrition import build_food_catalog_draft_tools
from nxtrep_backend.core.config import Settings
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.nutrition import CustomFoodPatchRequest


@pytest.mark.parametrize(
    "changes",
    [
        {"notes": "没有修改"},
        {"name": " ", "notes": "空名称"},
        {"kcal": -1, "notes": "负热量"},
        {"basis_amount_g": 0, "notes": "零基准"},
        {"kcal": None, "notes": "空热量"},
    ],
)
def test_food_patch_rejects_incomplete_or_invalid_changes(changes):
    with pytest.raises(ValidationError):
        CustomFoodPatchRequest.model_validate(changes)


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_runtime_exposes_only_the_requested_food_write_action(action, monkeypatch):
    context = MagicMock(spec=AgentToolContext)
    task = AgentIntentTask(
        task_type="food_catalog_draft",
        food_catalog_actions=[action],
        confidence="high",
        routing_reason="test",
    )
    captured = {}
    monkeypatch.setattr(
        "nxtrep_backend.agents.runtime.create_agent", lambda **kwargs: captured.update(kwargs)
    )
    build_agent(
        Settings(),
        tool_context=context,
        model=MagicMock(),
        tool_groups=groups_for_task(task),
        task_type=task.task_type,
        food_catalog_actions=task.food_catalog_actions,
    )
    names = {tool.name for tool in captured["tools"]}
    assert names & {
        "propose_custom_food",
        "propose_custom_food_update",
        "propose_custom_food_delete",
    } == {
        {
            "create": "propose_custom_food",
            "update": "propose_custom_food_update",
            "delete": "propose_custom_food_delete",
        }[action],
    }
    assert "read_custom_food" in names and "save_memory" not in names


@pytest.mark.asyncio
async def test_tools_require_read_and_latest_version_then_deduplicate_proposals():
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    food = SimpleNamespace(id=uuid4(), name="燕麦饼", brand=None)
    version = SimpleNamespace(version=2)
    context.nutrition_service.get_custom_food = AsyncMock(return_value=(food, version))
    context.nutrition_service.custom_food_snapshot.return_value = {"name": food.name}
    context.nutrition_service.propose_custom_food_change = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            operation_type="food_update",
            status="pending",
            before={},
            after={"food": {"name": food.name}},
            impact="待确认",
            expires_at=datetime.now(UTC),
            version=1,
        )
    )
    tools = {t.name: t for t in build_food_catalog_draft_tools(context)}
    args = {
        "food_id": str(food.id),
        "expected_version": 2,
        "changes": {"kcal": 320, "notes": "更正热量"},
    }
    denied = await tools["propose_custom_food_update"].ainvoke(args)
    assert denied["status"] == "needs_review"
    context.nutrition_service.propose_custom_food_change.assert_not_awaited()
    await tools["read_custom_food"].ainvoke({"food_id": str(food.id)})
    first = await tools["propose_custom_food_update"].ainvoke(args)
    repeated = await tools["propose_custom_food_update"].ainvoke(args)
    assert first == repeated and first["status"] == "confirmation_required"
    context.nutrition_service.propose_custom_food_change.assert_awaited_once()


@pytest.mark.asyncio
async def test_ambiguous_keyword_returns_choices_without_selecting_or_writing():
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    candidates = [
        (
            SimpleNamespace(id=uuid4(), name="燕麦饼", brand=brand),
            SimpleNamespace(basis_amount_g=100),
        )
        for brand in ["甲", "乙"]
    ]
    context.nutrition_service.search_foods = AsyncMock(return_value=(candidates, 2))
    context.nutrition_service.get_custom_food = AsyncMock()
    read = next(t for t in build_food_catalog_draft_tools(context) if t.name == "read_custom_food")
    result = await read.ainvoke({"keyword": "燕麦饼"})
    assert result["status"] == "needs_review" and len(result["candidates"]) == 2
    context.nutrition_service.get_custom_food.assert_not_awaited()
    assert context.nutrition_service.search_foods.await_args.kwargs["custom_only"] is True
