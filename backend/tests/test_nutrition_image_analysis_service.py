from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.nutrition_vision import (
    GlmFoodImageRecognizer,
    GlmFoodNutritionFallbackEstimator,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodImageRecognitionResult,
    FoodNutritionFallbackEstimate,
    FoodNutritionFallbackResult,
    FoodResponse,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionTotals,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.nutrition_image import (
    FoodCatalogMatcher,
    NutritionDraftCalculator,
    NutritionImageAnalysisService,
    NutritionImagePurposeError,
)


def make_image(purpose: ImagePurpose) -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=purpose,
        content_type="image/jpeg",
        data=b"sanitized-food-image",
    )


def make_food(name: str) -> FoodImageCandidate:
    return FoodImageCandidate(
        name=name,
        estimated_amount_g=Decimal("100"),
        amount_min_g=Decimal("80"),
        amount_max_g=Decimal("130"),
        confidence="medium",
    )


def make_totals(value: str = "0") -> NutritionTotals:
    nutrient = Decimal(value)
    return NutritionTotals(
        kcal=nutrient,
        protein_g=nutrient,
        carbs_g=nutrient,
        fat_g=nutrient,
    )


def make_range(value: str = "0") -> NutritionEstimateRange:
    totals = make_totals(value)
    return NutritionEstimateRange(
        minimum=totals,
        estimated=totals,
        maximum=totals,
    )


def make_calculation() -> NutritionDraftCalculation:
    return NutritionDraftCalculation(
        items=[],
        totals=make_range(),
        is_complete=True,
    )


def make_catalog_food(name: str) -> FoodResponse:
    return FoodResponse(
        id=uuid4(),
        food_version_id=uuid4(),
        name=name,
        basis_amount_g=Decimal("100"),
        kcal=Decimal("130"),
        protein_g=Decimal("2.7"),
        carbs_g=Decimal("28.2"),
        fat_g=Decimal("0.3"),
        source="usda",
        confidence="high",
    )


def make_dependencies() -> tuple[
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    recognizer = MagicMock(spec=GlmFoodImageRecognizer)
    recognizer.recognize = AsyncMock()
    fallback = MagicMock(spec=GlmFoodNutritionFallbackEstimator)
    fallback.estimate = AsyncMock()
    matcher = MagicMock(spec=FoodCatalogMatcher)
    matcher.match = AsyncMock()
    calculator = MagicMock(spec=NutritionDraftCalculator)
    return recognizer, fallback, matcher, calculator


@pytest.mark.asyncio
async def test_analysis_service_runs_multi_image_pipeline_and_fallbacks_only_missing_foods() -> (
    None
):
    recognizer, fallback, matcher, calculator = make_dependencies()
    user_id = uuid4()
    images = [
        make_image(ImagePurpose.NUTRITION_ENTRY),
        make_image(ImagePurpose.CHAT_ATTACHMENT),
    ]
    rice = make_food("熟白米饭")
    homemade_sauce = make_food("自制酱料")
    recognition = FoodImageRecognitionResult(foods=[rice, homemade_sauce])
    matches = [
        FoodCatalogMatchResult(
            detected=rice,
            status="matched",
            selected=make_catalog_food("熟白米饭"),
        ),
        FoodCatalogMatchResult(
            detected=homemade_sauce,
            status="not_found",
        ),
    ]
    fallback_result = FoodNutritionFallbackResult(
        estimates=[
            FoodNutritionFallbackEstimate(
                food_name="自制酱料",
                nutrition_per_100g=make_range("50"),
            )
        ]
    )
    calculation = make_calculation()
    recognizer.recognize.return_value = recognition
    matcher.match.return_value = matches
    fallback.estimate.return_value = fallback_result
    calculator.calculate.return_value = calculation
    service = NutritionImageAnalysisService(
        recognizer=recognizer,
        fallback_estimator=fallback,
        matcher=matcher,
        calculator=calculator,
    )

    result = await service.analyze(
        user_id=user_id,
        images=images,
        notes="米饭和自制酱料",
    )

    assert result.recognition == recognition
    assert result.calculation == calculation
    recognizer.recognize.assert_awaited_once_with(
        images=images,
        notes="米饭和自制酱料",
    )
    matcher.match.assert_awaited_once_with(
        user_id=user_id,
        foods=recognition.foods,
    )
    fallback.estimate.assert_awaited_once_with(
        images=images,
        foods=[homemade_sauce],
        notes="米饭和自制酱料",
    )
    calculator.calculate.assert_called_once_with(
        matches,
        fallback_result.estimates,
    )


@pytest.mark.asyncio
async def test_analysis_service_skips_fallback_when_catalog_resolves_all_foods() -> None:
    recognizer, fallback, matcher, calculator = make_dependencies()
    food = make_food("熟白米饭")
    recognition = FoodImageRecognitionResult(foods=[food])
    matches = [
        FoodCatalogMatchResult(
            detected=food,
            status="matched",
            selected=make_catalog_food("熟白米饭"),
        )
    ]
    recognizer.recognize.return_value = recognition
    matcher.match.return_value = matches
    calculator.calculate.return_value = make_calculation()
    service = NutritionImageAnalysisService(
        recognizer=recognizer,
        fallback_estimator=fallback,
        matcher=matcher,
        calculator=calculator,
    )

    await service.analyze(
        user_id=uuid4(),
        images=[make_image(ImagePurpose.NUTRITION_ENTRY)],
        notes=None,
    )

    fallback.estimate.assert_not_awaited()
    calculator.calculate.assert_called_once_with(matches, ())


@pytest.mark.asyncio
async def test_analysis_service_rejects_empty_images_before_dependencies() -> None:
    recognizer, fallback, matcher, calculator = make_dependencies()
    service = NutritionImageAnalysisService(
        recognizer=recognizer,
        fallback_estimator=fallback,
        matcher=matcher,
        calculator=calculator,
    )

    with pytest.raises(ValueError, match="resolved nutrition image"):
        await service.analyze(
            user_id=uuid4(),
            images=[],
            notes=None,
        )

    recognizer.recognize.assert_not_awaited()
    matcher.match.assert_not_awaited()
    fallback.estimate.assert_not_awaited()
    calculator.calculate.assert_not_called()


@pytest.mark.asyncio
async def test_analysis_service_rejects_body_image_before_model_call() -> None:
    recognizer, fallback, matcher, calculator = make_dependencies()
    service = NutritionImageAnalysisService(
        recognizer=recognizer,
        fallback_estimator=fallback,
        matcher=matcher,
        calculator=calculator,
    )

    with pytest.raises(NutritionImagePurposeError, match="nutrition"):
        await service.analyze(
            user_id=uuid4(),
            images=[make_image(ImagePurpose.BODY_PROGRESS)],
            notes=None,
        )

    recognizer.recognize.assert_not_awaited()
    matcher.match.assert_not_awaited()
