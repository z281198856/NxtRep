from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodImageRecognitionResult,
    FoodNutritionDraftItem,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionImageAnalysisResult,
    NutritionImageEstimateRequest,
    NutritionTotals,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.nutrition_image import (
    NutritionImageAnalysisService,
    NutritionImageDraftEstimator,
    NutritionImagePurposeError,
)


def make_request():
    return NutritionImageEstimateRequest(
        image_asset_id=uuid4(),
        meal_type="lunch",
        eaten_at=datetime.fromisoformat("2026-08-31T12:30:00+08:00"),
        notes="米饭大约一碗",
    )


def make_image(asset_id, purpose=ImagePurpose.NUTRITION_ENTRY):
    return ResolvedAgentImage(
        asset_id=asset_id,
        purpose=purpose,
        content_type="image/jpeg",
        data=b"sanitized-food-image",
    )


def make_recognition() -> FoodImageRecognitionResult:
    return FoodImageRecognitionResult(
        foods=[
            FoodImageCandidate(
                name="熟白米饭",
                estimated_amount_g=Decimal("180"),
                amount_min_g=Decimal("150"),
                amount_max_g=Decimal("220"),
                confidence="medium",
            ),
            FoodImageCandidate(
                name="鸡胸肉",
                estimated_amount_g=Decimal("120"),
                amount_min_g=Decimal("100"),
                amount_max_g=Decimal("150"),
                confidence="medium",
            ),
        ],
        assumptions=["重量均按熟重估计"],
        follow_up_questions=["烹饪时使用了多少油？"],
    )


def make_calculation(matches) -> NutritionDraftCalculation:
    zero = NutritionTotals(
        kcal=Decimal("0"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
    )
    totals = NutritionEstimateRange(
        minimum=zero,
        estimated=zero,
        maximum=zero,
    )
    return NutritionDraftCalculation(
        items=[FoodNutritionDraftItem(match=match, nutrition=None) for match in matches],
        totals=totals,
        is_complete=False,
    )


def make_dependencies():
    resolver = MagicMock(spec=AgentImageAssetResolver)
    resolver.resolve = AsyncMock()
    analysis_service = MagicMock(spec=NutritionImageAnalysisService)
    analysis_service.analyze = AsyncMock()
    return resolver, analysis_service


@pytest.mark.asyncio
async def test_estimator_delegates_analysis_and_builds_draft() -> None:
    resolver, analysis_service = make_dependencies()
    body = make_request()
    user_id = uuid4()
    image = make_image(body.image_asset_id)
    recognition = make_recognition()
    matches = [
        FoodCatalogMatchResult(detected=food, status="not_found") for food in recognition.foods
    ]
    calculation = make_calculation(matches)
    resolver.resolve.return_value = [image]
    analysis_service.analyze.return_value = NutritionImageAnalysisResult(
        recognition=recognition,
        calculation=calculation,
    )
    estimator = NutritionImageDraftEstimator(
        resolver=resolver,
        analysis_service=analysis_service,
    )

    result = await estimator.estimate(user_id=user_id, body=body)

    resolver.resolve.assert_awaited_once_with(
        user_id=user_id,
        asset_ids=[body.image_asset_id],
    )
    analysis_service.analyze.assert_awaited_once_with(
        user_id=user_id,
        images=[image],
        notes=body.notes,
    )
    assert result.image_asset_id == body.image_asset_id
    assert result.meal_type == "lunch"
    assert result.recognition == recognition
    assert result.calculation == calculation


@pytest.mark.asyncio
async def test_estimator_rejects_non_nutrition_image_before_model_call() -> None:
    resolver, analysis_service = make_dependencies()
    body = make_request()
    resolver.resolve.return_value = [make_image(body.image_asset_id, ImagePurpose.BODY_PROGRESS)]
    estimator = NutritionImageDraftEstimator(
        resolver=resolver,
        analysis_service=analysis_service,
    )

    with pytest.raises(NutritionImagePurposeError, match="nutrition_entry"):
        await estimator.estimate(user_id=uuid4(), body=body)

    analysis_service.analyze.assert_not_awaited()
