from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.nutrition import (
    FoodImageCandidate,
    FoodImageRecognitionResult,
    NutritionImageEstimateRequest,
)


def test_nutrition_image_estimate_request_accepts_meal_metadata() -> None:
    asset_id = uuid4()

    request = NutritionImageEstimateRequest(
        image_asset_id=asset_id,
        meal_type="lunch",
        eaten_at=datetime.fromisoformat("2026-08-30T12:30:00+08:00"),
        notes="米饭大约一碗",
    )

    assert request.image_asset_id == asset_id
    assert request.meal_type == "lunch"
    assert request.notes == "米饭大约一碗"


def test_nutrition_image_estimate_request_requires_eaten_at_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        NutritionImageEstimateRequest(
            image_asset_id=uuid4(),
            meal_type="lunch",
            eaten_at=datetime(2026, 8, 30, 12, 30),
        )


def test_food_image_candidate_accepts_an_estimated_amount_range() -> None:
    candidate = FoodImageCandidate(
        name="熟白米饭",
        estimated_amount_g=Decimal("180"),
        amount_min_g=Decimal("150"),
        amount_max_g=Decimal("220"),
        confidence="medium",
    )

    assert candidate.amount_min_g <= candidate.estimated_amount_g
    assert candidate.estimated_amount_g <= candidate.amount_max_g


def test_food_image_candidate_rejects_estimate_outside_range() -> None:
    with pytest.raises(ValidationError, match="amount"):
        FoodImageCandidate(
            name="熟白米饭",
            estimated_amount_g=Decimal("250"),
            amount_min_g=Decimal("150"),
            amount_max_g=Decimal("220"),
            confidence="medium",
        )


def test_food_image_recognition_result_accepts_multiple_foods_in_one_image() -> None:
    result = FoodImageRecognitionResult(
        foods=[
            FoodImageCandidate(
                name="熟白米饭",
                estimated_amount_g=Decimal("180"),
                amount_min_g=Decimal("150"),
                amount_max_g=Decimal("220"),
                confidence="high",
            ),
            FoodImageCandidate(
                name="鸡胸肉",
                estimated_amount_g=Decimal("120"),
                amount_min_g=Decimal("100"),
                amount_max_g=Decimal("150"),
                confidence="medium",
            ),
            FoodImageCandidate(
                name="西兰花",
                estimated_amount_g=Decimal("80"),
                amount_min_g=Decimal("60"),
                amount_max_g=Decimal("100"),
                confidence="medium",
            ),
        ],
        assumptions=["重量均按熟重估计"],
        follow_up_questions=["鸡胸肉和西兰花烹饪时用了多少油？"],
    )

    assert [food.name for food in result.foods] == [
        "熟白米饭",
        "鸡胸肉",
        "西兰花",
    ]
    assert len(result.foods) == 3


def test_food_image_recognition_result_contains_observations_not_nutrition_totals() -> None:
    result = FoodImageRecognitionResult(
        foods=[
            FoodImageCandidate(
                name="鸡胸肉",
                estimated_amount_g=Decimal("120"),
                amount_min_g=Decimal("100"),
                amount_max_g=Decimal("150"),
                confidence="high",
            )
        ],
        assumptions=["按熟重估计"],
        follow_up_questions=["烹饪时大约使用了多少油？"],
    )

    assert result.foods[0].name == "鸡胸肉"
    assert result.follow_up_questions == ["烹饪时大约使用了多少油？"]

    with pytest.raises(ValidationError):
        FoodImageRecognitionResult.model_validate(
            {
                "foods": [],
                "assumptions": [],
                "follow_up_questions": [],
                "kcal": 500,
            }
        )
