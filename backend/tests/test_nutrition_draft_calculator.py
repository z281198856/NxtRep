from decimal import Decimal
from uuid import uuid4

from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodNutritionFallbackEstimate,
    FoodResponse,
    NutritionEstimateRange,
    NutritionTotals,
)
from nxtrep_backend.services.nutrition_image import NutritionDraftCalculator


def make_detected_food(
    name: str,
    *,
    estimated: str,
    minimum: str,
    maximum: str,
) -> FoodImageCandidate:
    return FoodImageCandidate(
        name=name,
        estimated_amount_g=Decimal(estimated),
        amount_min_g=Decimal(minimum),
        amount_max_g=Decimal(maximum),
        confidence="medium",
    )


def make_catalog_food(
    name: str,
    *,
    kcal: str,
    protein: str,
    carbs: str,
    fat: str,
) -> FoodResponse:
    return FoodResponse(
        id=uuid4(),
        food_version_id=uuid4(),
        name=name,
        basis_amount_g=Decimal("100"),
        kcal=Decimal(kcal),
        protein_g=Decimal(protein),
        carbs_g=Decimal(carbs),
        fat_g=Decimal(fat),
        source="curated",
        confidence="high",
    )


def make_match(
    detected: FoodImageCandidate,
    selected: FoodResponse,
) -> FoodCatalogMatchResult:
    return FoodCatalogMatchResult(
        detected=detected,
        status="matched",
        selected=selected,
    )


def test_calculator_scales_each_nutrient_for_amount_range() -> None:
    match = make_match(
        make_detected_food(
            "鸡胸肉",
            estimated="120",
            minimum="100",
            maximum="150",
        ),
        make_catalog_food(
            "鸡胸肉",
            kcal="165",
            protein="31",
            carbs="0",
            fat="3.6",
        ),
    )

    result = NutritionDraftCalculator().calculate([match])

    nutrients = result.items[0].nutrition
    assert nutrients is not None
    assert nutrients.minimum.kcal == Decimal("165")
    assert nutrients.estimated.kcal == Decimal("198")
    assert nutrients.maximum.kcal == Decimal("247.5")
    assert nutrients.estimated.protein_g == Decimal("37.2")
    assert nutrients.estimated.fat_g == Decimal("4.32")
    assert result.is_complete is True


def test_calculator_sums_multiple_foods_into_meal_totals() -> None:
    rice = make_match(
        make_detected_food(
            "熟白米饭",
            estimated="200",
            minimum="180",
            maximum="220",
        ),
        make_catalog_food(
            "熟白米饭",
            kcal="116",
            protein="2.6",
            carbs="25.9",
            fat="0.3",
        ),
    )
    chicken = make_match(
        make_detected_food(
            "鸡胸肉",
            estimated="100",
            minimum="80",
            maximum="120",
        ),
        make_catalog_food(
            "鸡胸肉",
            kcal="165",
            protein="31",
            carbs="0",
            fat="3.6",
        ),
    )

    result = NutritionDraftCalculator().calculate([rice, chicken])

    assert result.totals.estimated.kcal == Decimal("397")
    assert result.totals.estimated.protein_g == Decimal("36.2")
    assert result.totals.estimated.carbs_g == Decimal("51.8")
    assert result.totals.estimated.fat_g == Decimal("4.2")
    assert result.is_complete is True


def test_calculator_keeps_unmatched_food_without_inventing_nutrition() -> None:
    matched = make_match(
        make_detected_food(
            "熟白米饭",
            estimated="200",
            minimum="180",
            maximum="220",
        ),
        make_catalog_food(
            "熟白米饭",
            kcal="116",
            protein="2.6",
            carbs="25.9",
            fat="0.3",
        ),
    )
    unresolved = FoodCatalogMatchResult(
        detected=make_detected_food(
            "自制杂粮饼",
            estimated="100",
            minimum="80",
            maximum="130",
        ),
        status="not_found",
    )

    result = NutritionDraftCalculator().calculate([matched, unresolved])

    assert result.items[0].nutrition is not None
    assert result.items[1].nutrition is None
    assert result.totals.estimated.kcal == Decimal("232")
    assert result.is_complete is False
    assert result.requires_confirmation is True


def test_calculator_scales_fallback_per_100g_to_detected_portion() -> None:
    detected = make_detected_food(
        "自制杂粮饼",
        estimated="150",
        minimum="100",
        maximum="200",
    )
    match = FoodCatalogMatchResult(
        detected=detected,
        status="not_found",
    )
    fallback = FoodNutritionFallbackEstimate(
        food_name="自制杂粮饼",
        nutrition_per_100g=NutritionEstimateRange(
            minimum=NutritionTotals(
                kcal=Decimal("180"),
                protein_g=Decimal("5"),
                carbs_g=Decimal("30"),
                fat_g=Decimal("4"),
            ),
            estimated=NutritionTotals(
                kcal=Decimal("240"),
                protein_g=Decimal("7"),
                carbs_g=Decimal("38"),
                fat_g=Decimal("6"),
            ),
            maximum=NutritionTotals(
                kcal=Decimal("300"),
                protein_g=Decimal("10"),
                carbs_g=Decimal("48"),
                fat_g=Decimal("10"),
            ),
        ),
        assumptions=["按含少量食用油的杂粮面饼估计"],
        follow_up_questions=["主要使用了哪些面粉？"],
    )

    result = NutritionDraftCalculator().calculate([match], [fallback])

    item = result.items[0]
    assert item.nutrition is not None
    assert item.nutrition.minimum.kcal == Decimal("180")
    assert item.nutrition.estimated.kcal == Decimal("360")
    assert item.nutrition.maximum.kcal == Decimal("600")
    assert item.source == "model_estimated"
    assert item.confidence == "low"
    assert item.requires_confirmation is True
    assert result.totals.estimated.kcal == Decimal("360")
    assert result.is_complete is True
    assert result.requires_confirmation is True


def test_calculator_returns_incomplete_zero_totals_for_no_detected_food() -> None:
    result = NutritionDraftCalculator().calculate([])

    assert result.items == []
    assert result.totals.estimated.kcal == Decimal("0")
    assert result.totals.estimated.protein_g == Decimal("0")
    assert result.is_complete is False
