from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call
from uuid import UUID, uuid4

import pytest

from nxtrep_backend.db.models import Food, FoodVersion
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import FoodImageCandidate
from nxtrep_backend.services.nutrition_image import FoodCatalogMatcher


def make_detected_food(name: str) -> FoodImageCandidate:
    return FoodImageCandidate(
        name=name,
        estimated_amount_g=Decimal("120"),
        amount_min_g=Decimal("100"),
        amount_max_g=Decimal("150"),
        confidence="medium",
    )


def make_catalog_food(
    name: str,
    *,
    owner_user_id: UUID | None = None,
) -> tuple[Food, FoodVersion]:
    food = Food(
        id=uuid4(),
        owner_user_id=owner_user_id,
        name=name,
        brand=None,
        region="CN",
        state="cooked",
    )
    version = FoodVersion(
        id=uuid4(),
        food_id=food.id,
        version=1,
        basis_amount_g=Decimal("100"),
        kcal=Decimal("165"),
        protein_g=Decimal("31"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("3.6"),
        source="curated",
        confidence="high",
    )
    return food, version


def make_repository() -> MagicMock:
    repository = MagicMock(spec=SqlAlchemyNutritionRepository)
    repository.search_foods = AsyncMock()
    repository.find_foods_by_exact_alias = AsyncMock(return_value=[])
    return repository


@pytest.mark.asyncio
async def test_matcher_selects_one_exact_catalog_match() -> None:
    repository = make_repository()
    exact = make_catalog_food("鸡胸肉")
    similar = make_catalog_food("鸡胸肉沙拉")
    repository.search_foods.return_value = ([exact, similar], 2)
    matcher = FoodCatalogMatcher(repository)

    result = await matcher.match(
        user_id=uuid4(),
        foods=[make_detected_food(" 鸡胸肉 ")],
    )

    assert len(result) == 1
    assert result[0].status == "matched"
    assert result[0].selected is not None
    assert result[0].selected.food_version_id == exact[1].id
    assert result[0].alternatives == []


@pytest.mark.asyncio
async def test_matcher_requires_confirmation_for_similar_catalog_results() -> None:
    repository = make_repository()
    cooked = make_catalog_food("熟鸡胸肉")
    salad = make_catalog_food("鸡胸肉沙拉")
    repository.search_foods.return_value = ([cooked, salad], 2)
    matcher = FoodCatalogMatcher(repository)

    result = await matcher.match(
        user_id=uuid4(),
        foods=[make_detected_food("鸡胸肉")],
    )

    assert result[0].status == "needs_confirmation"
    assert result[0].selected is None
    assert [item.food_version_id for item in result[0].alternatives] == [
        cooked[1].id,
        salad[1].id,
    ]


@pytest.mark.asyncio
async def test_matcher_selects_one_exact_alias_match() -> None:
    repository = make_repository()
    rice = make_catalog_food("熟白米饭")
    repository.search_foods.return_value = ([rice], 1)
    repository.find_foods_by_exact_alias.return_value = [rice]

    result = await FoodCatalogMatcher(repository).match(
        user_id=uuid4(),
        foods=[make_detected_food("米饭")],
    )

    assert result[0].status == "matched"
    assert result[0].selected.food_version_id == rice[1].id


@pytest.mark.asyncio
async def test_matcher_marks_food_missing_when_catalog_has_no_candidates() -> None:
    repository = make_repository()
    repository.search_foods.return_value = ([], 0)
    matcher = FoodCatalogMatcher(repository)

    result = await matcher.match(
        user_id=uuid4(),
        foods=[make_detected_food("自制杂粮饼")],
    )

    assert result[0].status == "not_found"
    assert result[0].selected is None
    assert result[0].alternatives == []


@pytest.mark.asyncio
async def test_matcher_searches_each_detected_food_in_original_order() -> None:
    repository = make_repository()
    rice = make_catalog_food("熟白米饭")
    chicken = make_catalog_food("鸡胸肉")
    repository.search_foods.side_effect = [([rice], 1), ([chicken], 1)]
    matcher = FoodCatalogMatcher(repository)
    user_id = uuid4()

    result = await matcher.match(
        user_id=user_id,
        foods=[
            make_detected_food("熟白米饭"),
            make_detected_food("鸡胸肉"),
        ],
    )

    assert [item.detected.name for item in result] == ["熟白米饭", "鸡胸肉"]
    assert repository.search_foods.await_args_list == [
        call(user_id, "熟白米饭", None, None, 1, 5),
        call(user_id, "鸡胸肉", None, None, 1, 5),
    ]
