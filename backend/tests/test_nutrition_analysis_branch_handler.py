from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodImageRecognitionResult,
    FoodNutritionDraftItem,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionImageAnalysisResult,
    NutritionTotals,
)
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.nutrition import (
    NutritionAnalysisBranchHandler,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.nutrition_image import (
    NutritionImageAnalysisService,
)


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.CHAT_ATTACHMENT,
        content_type="image/jpeg",
        data=b"sanitized-food-image",
    )


def make_task(
    *,
    task_type: str = "nutrition_analysis",
    asset_ids=None,
    missing_fields=None,
) -> AgentIntentTask:
    return AgentIntentTask(
        task_type=task_type,
        asset_ids=asset_ids or [],
        required_context=[],
        missing_fields=missing_fields or [],
        confidence="high",
        routing_reason="The user asked for food image analysis",
    )


def make_input(
    *,
    task_type: str = "nutrition_analysis",
    images=(),
    missing_fields=None,
) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message="分析这顿饭，米饭大约半碗",
        task=make_task(
            task_type=task_type,
            asset_ids=[image.asset_id for image in images],
            missing_fields=missing_fields,
        ),
        images=tuple(images),
    )


def zero_totals() -> NutritionTotals:
    return NutritionTotals(
        kcal=Decimal("0"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
    )


def make_analysis(*, with_foods: bool) -> NutritionImageAnalysisResult:
    foods = []

    if with_foods:
        foods = [
            FoodImageCandidate(
                name="米饭",
                estimated_amount_g=Decimal("100"),
                amount_min_g=Decimal("80"),
                amount_max_g=Decimal("130"),
                confidence="medium",
            ),
            FoodImageCandidate(
                name="鸡胸肉",
                estimated_amount_g=Decimal("120"),
                amount_min_g=Decimal("100"),
                amount_max_g=Decimal("150"),
                confidence="medium",
            ),
        ]

    matches = [
        FoodCatalogMatchResult(
            detected=food,
            status="not_found",
        )
        for food in foods
    ]
    totals = NutritionEstimateRange(
        minimum=zero_totals(),
        estimated=zero_totals(),
        maximum=zero_totals(),
    )

    return NutritionImageAnalysisResult(
        recognition=FoodImageRecognitionResult(foods=foods),
        calculation=NutritionDraftCalculation(
            items=[
                FoodNutritionDraftItem(
                    match=match,
                    requires_confirmation=True,
                )
                for match in matches
            ],
            totals=totals,
            is_complete=False,
            requires_confirmation=bool(foods),
        ),
    )


def make_service() -> MagicMock:
    service = MagicMock(spec=NutritionImageAnalysisService)
    service.analyze = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_handler_returns_multiple_foods_and_confirmation_flag() -> None:
    service = make_service()
    analysis = make_analysis(with_foods=True)
    service.analyze.return_value = analysis
    image = make_image()
    branch_input = make_input(images=(image,))
    handler = NutritionAnalysisBranchHandler(service)

    result = await handler.execute(branch_input)

    service.analyze.assert_awaited_once_with(
        user_id=branch_input.user_id,
        images=(image,),
        notes=branch_input.message,
    )
    assert result.status == "completed"
    assert result.result == analysis.model_dump(mode="json")
    assert len(result.result["recognition"]["foods"]) == 2
    assert result.requires_confirmation is True


@pytest.mark.asyncio
async def test_handler_requests_food_image_before_analysis() -> None:
    service = make_service()
    branch_input = make_input(
        missing_fields=["food_images", "meal_context"],
    )
    handler = NutritionAnalysisBranchHandler(service)

    result = await handler.execute(branch_input)

    assert result.status == "needs_input"
    assert result.missing_fields == ["food_images", "meal_context"]
    service.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_requests_clearer_input_when_no_food_is_recognized() -> None:
    service = make_service()
    analysis = make_analysis(with_foods=False)
    service.analyze.return_value = analysis
    image = make_image()
    branch_input = make_input(images=(image,))
    handler = NutritionAnalysisBranchHandler(service)

    result = await handler.execute(branch_input)

    assert result.status == "needs_input"
    assert result.result == analysis.model_dump(mode="json")
    assert result.missing_fields == ["identifiable_food"]
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_handler_rejects_non_nutrition_task() -> None:
    service = make_service()
    branch_input = make_input(task_type="body_assessment")
    handler = NutritionAnalysisBranchHandler(service)

    with pytest.raises(ValueError, match="nutrition_analysis task"):
        await handler.execute(branch_input)

    service.analyze.assert_not_awaited()
