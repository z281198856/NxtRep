from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr, ValidationError
from test_nutrition_image_analysis_service import (
    make_catalog_food,
    make_food,
    make_image,
    make_range,
)
from test_nutrition_image_draft_estimator import make_dependencies, make_request

from nxtrep_backend.agents.nutrition_vision import GlmFoodImageRecognizer
from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.models import (
    GlmVisionModelGateway,
    build_food_fallback_vision_model,
    build_food_vision_model,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageRecognitionResult,
    FoodNutritionFallbackEstimate,
    FoodNutritionFallbackResult,
    NutritionImageEstimateRequest,
)
from nxtrep_backend.services.nutrition_image import (
    NutritionDraftCalculator,
    NutritionImageAnalysisService,
    NutritionImageDraftEstimator,
    NutritionImagePurposeError,
)


def test_food_quality_policy_does_not_change_body_model_or_silently_downgrade():
    settings = Settings(
        _env_file=None,
        glm_api_key=SecretStr("test-key"),
        glm_vision_model="glm-4.6v-flash",
        glm_vision_fallback_model="glm-4v-flash",
        food_vision_model="glm-4.6v",
        food_vision_fallback_model=None,
    )
    food = build_food_vision_model(settings)
    body = GlmVisionModelGateway(settings).build()
    assert food.model_name == "glm-4.6v" and food.request_timeout == 40
    assert food.max_retries == 0
    assert food.extra_body == {"thinking": {"type": "disabled"}}
    assert body.extra_body is None
    assert body.model_name == "glm-4.6v-flash" and body.max_retries == 1
    assert build_food_fallback_vision_model(settings) is None
    settings.food_vision_fallback_model = "glm-4.6v-flash"
    fallback = build_food_fallback_vision_model(settings)
    assert fallback.model_name == "glm-4.6v-flash" and fallback.request_timeout == 15
    assert fallback.max_retries == 0


@pytest.mark.asyncio
async def test_unmeasured_photo_portions_are_uncertain_without_clamping_grams():
    food = make_food("熟白米饭")
    food.estimated_amount_g, food.amount_min_g, food.amount_max_g = map(
        Decimal, ("400", "350", "450")
    )
    food.portion_confidence = "high"
    model = MagicMock(
        ainvoke=AsyncMock(
            return_value=AIMessage(
                content=FoodImageRecognitionResult(foods=[food]).model_dump_json()
            )
        )
    )
    result = await GlmFoodImageRecognizer(model).recognize(
        images=[make_image(ImagePurpose.NUTRITION_ENTRY)], notes=None
    )
    assert result.foods[0].portion_confidence == "low"
    assert result.foods[0].estimated_amount_g == 400
    assert result.foods[0].amount_min_g == 350 and result.foods[0].amount_max_g == 450
    assert result.foods[0].portion_basis is None  # Do not fabricate a measurement basis.


@pytest.mark.asyncio
async def test_corrections_keep_names_and_grams_and_recompute_nutrition_without_vision():
    rice, meat = make_food("熟白米饭"), make_food("炖牛肉")
    rice.estimated_amount_g = rice.amount_min_g = rice.amount_max_g = 200
    recognizer = MagicMock(recognize=AsyncMock())
    matcher = MagicMock(
        match=AsyncMock(
            return_value=[
                FoodCatalogMatchResult(
                    detected=rice, status="matched", selected=make_catalog_food(rice.name)
                ),
                FoodCatalogMatchResult(detected=meat, status="not_found"),
            ]
        )
    )
    fallback = MagicMock(
        estimate=AsyncMock(
            return_value=FoodNutritionFallbackResult(
                estimates=[
                    FoodNutritionFallbackEstimate(
                        food_name=meat.name, nutrition_per_100g=make_range("80")
                    )
                ]
            )
        )
    )
    result = await NutritionImageAnalysisService(
        recognizer=recognizer,
        matcher=matcher,
        fallback_estimator=fallback,
        calculator=NutritionDraftCalculator(),
    ).analyze(
        user_id=uuid4(),
        images=[make_image(ImagePurpose.NUTRITION_ENTRY)],
        notes="少油",
        reviewed_foods=[rice, meat],
    )
    recognizer.recognize.assert_not_awaited()
    assert [food.name for food in result.recognition.foods] == [rice.name, meat.name]
    assert result.calculation.totals.estimated.kcal == 340  # 200g rice + 100g corrected meat
    assert result.calculation.items[1].match.detected.name == "炖牛肉"
    assert fallback.estimate.call_args.kwargs["foods"] == [meat]
    assert "不代表实际称重" in result.recognition.assumptions[0]


@pytest.mark.asyncio
async def test_reviewed_foods_still_require_owned_ready_nutrition_image():
    resolver, analysis = make_dependencies()
    body = make_request().model_copy(update={"reviewed_foods": [make_food("熟白米饭")]})
    resolver.resolve.return_value = [make_image(ImagePurpose.BODY_PROGRESS)]
    estimator = NutritionImageDraftEstimator(resolver=resolver, analysis_service=analysis)
    user_id = uuid4()
    with pytest.raises(NutritionImagePurposeError):
        await estimator.estimate(user_id=user_id, body=body)
    resolver.resolve.assert_awaited_once_with(user_id=user_id, asset_ids=[body.image_asset_id])
    analysis.analyze.assert_not_awaited()


@pytest.mark.parametrize(
    "foods",
    [
        [],
        [
            {
                "name": "米饭",
                "estimated_amount_g": 0,
                "amount_min_g": 0,
                "amount_max_g": 0,
                "confidence": "low",
            }
        ],
        [
            {
                "name": "米饭",
                "estimated_amount_g": 100,
                "amount_min_g": 120,
                "amount_max_g": 150,
                "confidence": "low",
            }
        ],
    ],
)
def test_invalid_corrections_are_rejected_before_model_execution(foods):
    with pytest.raises(ValidationError):
        NutritionImageEstimateRequest.model_validate(
            {**make_request().model_dump(mode="json"), "reviewed_foods": foods}
        )
