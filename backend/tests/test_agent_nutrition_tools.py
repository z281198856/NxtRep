from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.nutrition import (
    build_food_catalog_draft_tools,
    build_nutrition_draft_tools,
    build_nutrition_read_tools,
)
from nxtrep_backend.services.nutrition import NutritionService


def make_context() -> MagicMock:
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    context.nutrition_service = MagicMock(spec=NutritionService)
    context.nutrition_service.search_foods = AsyncMock()
    context.nutrition_service.propose_entry = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_search_food_candidates_returns_amount_basis() -> None:
    context = make_context()
    food = SimpleNamespace(
        id=uuid4(),
        name="鸡胸肉",
        brand=None,
        state="cooked",
    )
    version = SimpleNamespace(
        id=uuid4(),
        basis_amount_g=100,
        kcal=165,
        protein_g=31,
        carbs_g=0,
        fat_g=3.6,
        source="usda",
        confidence="high",
    )
    context.nutrition_service.search_foods.return_value = ([(food, version)], 1)
    current_tool = build_nutrition_read_tools(context)[0]

    result = await current_tool.ainvoke({"keyword": "鸡胸", "state": "cooked", "limit": 5})

    assert result["foods"][0]["basis_amount_g"] == "100"
    assert result["foods"][0]["protein_g"] == "31"
    context.nutrition_service.search_foods.assert_awaited_once_with(
        user_id=context.user_id,
        keyword="鸡胸",
        region=None,
        state="cooked",
        page=1,
        page_size=5,
    )


@pytest.mark.asyncio
async def test_food_search_budget_stops_synonym_loop_without_claiming_a_match():
    context = make_context()
    context.nutrition_service.search_foods.return_value = ([], 0)
    search = build_nutrition_read_tools(context)[0]
    for keyword in ("鸡胗饭", "泡椒鸡胗", "鸡肫", "鸡胗", "泡椒鸡肫", "熟鸡胗"):
        assert (await search.ainvoke({"keyword": keyword}))["status"] == "available"
    limited = await search.ainvoke({"keyword": "泡椒鸡胗饭"})
    assert limited["status"] == "unavailable" and limited["foods"] == []
    assert limited["error_code"] == "FOOD_SEARCH_LIMIT"
    assert "估算" in limited["message"]
    assert context.nutrition_service.search_foods.await_count == 6


@pytest.mark.asyncio
async def test_repeated_food_proposal_reuses_card_within_one_request():
    context = make_context()
    food = {
        "name": "自制燕麦饼",
        "brand": None,
        "basis_amount_g": "100",
        "kcal": "300",
        "protein_g": "10",
        "carbs_g": "40",
        "fat_g": "11",
        "notes": "每100克暂定估算",
    }
    context.nutrition_service.propose_custom_food = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            operation_type="food_create",
            status="pending",
            before=None,
            after={"food": food},
            impact="添加食品",
            expires_at=datetime.now(UTC),
            version=1,
        )
    )
    propose = build_food_catalog_draft_tools(context)[0]
    first = await propose.ainvoke({"food": food})
    second = await propose.ainvoke({"food": dict(food)})
    assert first["confirmation"]["confirmation_id"] == second["confirmation"]["confirmation_id"]
    context.nutrition_service.propose_custom_food.assert_awaited_once()


@pytest.mark.asyncio
async def test_propose_nutrition_entry_requires_confirmation() -> None:
    context = make_context()
    confirmation = SimpleNamespace(
        id=uuid4(),
        operation_type="nutrition_entry_create",
        status="pending",
        before=None,
        after={"entry": {}},
        impact="save meal",
        expires_at=None,
        version=1,
    )
    context.nutrition_service.propose_entry.return_value = confirmation
    current_tool = next(
        item
        for item in build_nutrition_draft_tools(context)
        if item.name == "propose_nutrition_entry"
    )

    result = await current_tool.ainvoke(
        {
            "meal_type": "lunch",
            "eaten_at": datetime(2026, 9, 3, 12, tzinfo=UTC).isoformat(),
            "items": [
                {
                    "amount_g": "150",
                    "name": "米饭",
                    "basis_amount_g": "100",
                    "kcal": "116",
                    "protein_g": "2.6",
                    "carbs_g": "25.9",
                    "fat_g": "0.3",
                    "source": "vision_estimate",
                    "confidence": "medium",
                }
            ],
        }
    )

    assert result["status"] == "confirmation_required"
    assert result["confirmation"]["operation_type"] == "nutrition_entry_create"
    request = context.nutrition_service.propose_entry.await_args.kwargs["body"]
    assert request.items[0].amount_g == 150
    assert request.items[0].source == "model_estimated"
    assert request.items[0].confidence == "low"
    assert "draft" in result
