from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from nxtrep_backend.agents.nutrition_vision import (
    FoodNutritionFallbackError,
    GlmFoodNutritionFallbackEstimator,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodImageCandidate,
    FoodNutritionFallbackEstimate,
    FoodNutritionFallbackResult,
    NutritionEstimateRange,
    NutritionTotals,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.NUTRITION_ENTRY,
        content_type="image/jpeg",
        data=b"sanitized-food-image",
    )


def make_detected_food(name: str) -> FoodImageCandidate:
    return FoodImageCandidate(
        name=name,
        estimated_amount_g=Decimal("100"),
        amount_min_g=Decimal("80"),
        amount_max_g=Decimal("130"),
        confidence="low",
    )


def make_nutrition_range() -> NutritionEstimateRange:
    return NutritionEstimateRange(
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
    )


def make_fallback_result() -> FoodNutritionFallbackResult:
    return FoodNutritionFallbackResult(
        estimates=[
            FoodNutritionFallbackEstimate(
                food_name="自制杂粮饼",
                basis_amount_g=Decimal("100"),
                nutrition_per_100g=make_nutrition_range(),
                assumptions=["按含少量食用油的杂粮面饼估计"],
                follow_up_questions=["主要使用了哪些面粉？"],
            ),
            FoodNutritionFallbackEstimate(
                food_name="家庭自制酱料",
                basis_amount_g=Decimal("100"),
                nutrition_per_100g=make_nutrition_range(),
                assumptions=["无法确认糖和油的比例"],
                follow_up_questions=["酱料中是否添加了糖和油？"],
            ),
        ]
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    model = MagicMock(spec=BaseChatModel)
    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock()
    model.with_structured_output.return_value = structured_model
    return model, structured_model


def test_fallback_schema_forces_low_confidence_and_confirmation() -> None:
    estimate = make_fallback_result().estimates[0]

    assert estimate.source == "model_estimated"
    assert estimate.confidence == "low"
    assert estimate.requires_confirmation is True
    assert estimate.nutrition_per_100g.estimated.kcal == Decimal("240")

    with pytest.raises(ValidationError, match="100"):
        FoodNutritionFallbackEstimate(
            food_name="自制杂粮饼",
            basis_amount_g=Decimal("80"),
            nutrition_per_100g=make_nutrition_range(),
        )


def test_fallback_estimator_uses_function_calling_structured_output() -> None:
    model, _ = make_dependencies()

    GlmFoodNutritionFallbackEstimator(model)

    model.with_structured_output.assert_called_once_with(
        FoodNutritionFallbackResult,
        method="function_calling",
        include_raw=True,
    )


@pytest.mark.asyncio
async def test_fallback_estimator_handles_multiple_unknown_foods_in_one_call() -> None:
    model, structured_model = make_dependencies()
    expected = make_fallback_result()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }
    estimator = GlmFoodNutritionFallbackEstimator(model)
    foods = [
        make_detected_food("自制杂粮饼"),
        make_detected_food("家庭自制酱料"),
    ]

    result = await estimator.estimate(
        images=[make_image()],
        foods=foods,
        notes="饼和酱都是自己做的",
    )

    assert result == expected
    assert [item.food_name for item in result.estimates] == [
        "自制杂粮饼",
        "家庭自制酱料",
    ]
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_prompt_contains_names_notes_and_per_100g_boundary() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": FoodNutritionFallbackResult(estimates=[make_fallback_result().estimates[0]]),
        "parsing_error": None,
    }
    estimator = GlmFoodNutritionFallbackEstimator(model)

    await estimator.estimate(
        images=[make_image()],
        foods=[make_detected_food("自制杂粮饼")],
        notes="没有包装标签",
    )

    messages = structured_model.ainvoke.await_args.args[0]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    prompt = messages[0].content[0]["text"]
    assert "自制杂粮饼" in prompt
    assert "没有包装标签" in prompt
    assert "每100克" in prompt
    assert "低置信度" in prompt


@pytest.mark.asyncio
async def test_fallback_estimator_rejects_missing_or_extra_food_results() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": FoodNutritionFallbackResult(estimates=[make_fallback_result().estimates[0]]),
        "parsing_error": None,
    }
    estimator = GlmFoodNutritionFallbackEstimator(model)

    with pytest.raises(FoodNutritionFallbackError, match="requested foods"):
        await estimator.estimate(
            images=[make_image()],
            foods=[
                make_detected_food("自制杂粮饼"),
                make_detected_food("家庭自制酱料"),
            ],
            notes=None,
        )


@pytest.mark.asyncio
async def test_fallback_estimator_reports_structured_output_failure() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": None,
        "parsing_error": ValueError("invalid nutrition output"),
    }
    estimator = GlmFoodNutritionFallbackEstimator(model)

    with pytest.raises(FoodNutritionFallbackError, match="structured output"):
        await estimator.estimate(
            images=[make_image()],
            foods=[make_detected_food("自制杂粮饼")],
            notes=None,
        )
