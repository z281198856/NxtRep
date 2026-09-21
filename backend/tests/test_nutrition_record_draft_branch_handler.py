from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentContextHints,
    AgentIntentTask,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodImageRecognitionResult,
    FoodNutritionDraftItem,
    FoodResponse,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionImageAnalysisResult,
    NutritionTotals,
)
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.nutrition_record import (
    NutritionRecordDraftBranchHandler,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.nutrition_image import NutritionImageAnalysisService


def make_analysis() -> NutritionImageAnalysisResult:
    detected = FoodImageCandidate(
        name="熟白米饭",
        estimated_amount_g=Decimal("150"),
        amount_min_g=Decimal("120"),
        amount_max_g=Decimal("180"),
        confidence="medium",
    )
    selected = FoodResponse(
        id=uuid4(),
        food_version_id=uuid4(),
        name="熟白米饭",
        basis_amount_g=Decimal("100"),
        kcal=Decimal("130"),
        protein_g=Decimal("2.69"),
        carbs_g=Decimal("28.17"),
        fat_g=Decimal("0.28"),
        source="usda",
        confidence="high",
    )
    match = FoodCatalogMatchResult(
        detected=detected,
        status="matched",
        selected=selected,
    )
    totals = NutritionTotals(
        kcal=Decimal("195"),
        protein_g=Decimal("4.035"),
        carbs_g=Decimal("42.255"),
        fat_g=Decimal("0.42"),
    )
    estimate = NutritionEstimateRange(
        minimum=totals,
        estimated=totals,
        maximum=totals,
    )
    return NutritionImageAnalysisResult(
        recognition=FoodImageRecognitionResult(foods=[detected]),
        calculation=NutritionDraftCalculation(
            items=[
                FoodNutritionDraftItem(
                    match=match,
                    nutrition=estimate,
                    source="usda",
                    confidence="high",
                )
            ],
            totals=estimate,
            is_complete=True,
        ),
    )


def make_input(*, prior_results=(), with_hints: bool = True) -> AgentBranchInput:
    image = ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.NUTRITION_ENTRY,
        content_type="image/jpeg",
        data=b"food",
    )
    hints = (
        AgentContextHints(
            meal_type="lunch",
            occurred_at=datetime(2026, 9, 8, 12, 30, tzinfo=UTC),
        )
        if with_hints
        else AgentContextHints()
    )
    return AgentBranchInput(
        user_id=uuid4(),
        message="把这顿午饭记录下来",
        task=AgentIntentTask(
            task_type="nutrition_record_draft",
            asset_ids=[image.asset_id],
            confidence="high",
            routing_reason="record meal",
        ),
        images=(image,),
        context_hints=hints,
        prior_results=tuple(prior_results),
    )


def make_handler() -> tuple[
    NutritionRecordDraftBranchHandler,
    MagicMock,
    MagicMock,
]:
    analysis_service = MagicMock(spec=NutritionImageAnalysisService)
    analysis_service.analyze = AsyncMock()
    nutrition_service = MagicMock(spec=NutritionService)
    nutrition_service.propose_entry = AsyncMock()
    return (
        NutritionRecordDraftBranchHandler(analysis_service, nutrition_service),
        analysis_service,
        nutrition_service,
    )


@pytest.mark.asyncio
async def test_record_draft_reuses_prior_analysis_and_returns_confirmation_card() -> None:
    analysis = make_analysis()
    branch_input = make_input(
        prior_results=[
            AgentBranchResult(
                task_type="nutrition_analysis",
                asset_ids=[],
                status="completed",
                result=analysis.model_dump(mode="json"),
            )
        ]
    )
    branch_input.prior_results[0].asset_ids = [branch_input.images[0].asset_id]
    handler, analysis_service, nutrition_service = make_handler()
    confirmation_id = uuid4()
    nutrition_service.propose_entry.return_value = SimpleNamespace(
        id=confirmation_id,
        operation_type="nutrition_entry_create",
        status="pending",
        before=None,
        after={"entry": {}},
        impact="save nutrition entry",
        expires_at=datetime(2026, 9, 9, tzinfo=UTC),
        version=1,
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert result.requires_confirmation is True
    assert result.confirmation_cards[0].confirmation_id == confirmation_id
    assert result.result["draft"]["items"][0]["amount_g"] == "150"
    analysis_service.analyze.assert_not_awaited()
    nutrition_service.propose_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_draft_analyzes_image_but_requests_missing_meal_metadata() -> None:
    branch_input = make_input(with_hints=False)
    handler, analysis_service, nutrition_service = make_handler()
    analysis_service.analyze.return_value = make_analysis()

    result = await handler.execute(branch_input)

    assert result.status == "needs_input"
    assert result.missing_fields == ["meal_type", "eaten_at"]
    assert "analysis" in result.result
    analysis_service.analyze.assert_awaited_once()
    nutrition_service.propose_entry.assert_not_awaited()
