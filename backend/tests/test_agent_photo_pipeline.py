"""Food review and business approval are distinct across the complete photo pipeline."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_nutrition_record_draft_branch_handler import make_analysis, make_handler, make_input

from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentChatRequest,
    AgentContextHints,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_handlers.nutrition import NutritionAnalysisBranchHandler
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.agent_safety import AgentExecutionSafetyValidator
from nxtrep_backend.services.conversation import AgentConversationContext


def estimated_analysis():
    analysis = make_analysis()
    analysis.calculation.requires_confirmation = True
    item = analysis.calculation.items[0]
    item.match.selected = None
    item.match.status = "not_found"
    item.source, item.confidence, item.requires_confirmation = "model_estimated", "low", True
    item.assumptions = ["按常见份量和中等用油估算"]
    analysis.recognition.assumptions = ["照片份量没有称重"]
    return analysis


def proposed_card():
    return SimpleNamespace(
        id=uuid4(),
        operation_type="nutrition_entry_create",
        status="pending",
        before=None,
        after={},
        impact="确认后保存",
        version=1,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_photo_natural_yesterday_lunch_and_estimate_form_one_valid_confirmation():
    original = make_input(with_hints=False)
    image = original.images[0]
    record_handler, vision, nutrition = make_handler()
    vision.analyze.return_value = estimated_analysis()
    nutrition.propose_entry.return_value = proposed_card()
    plan = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type=kind,
                confidence="high",
                routing_reason="照片识别并记录昨天午餐",
                asset_ids=[image.asset_id],
                task_update=AgentTaskUpdate(
                    transition="new", parameters={"date": "2026-10-16", "meal_type": "lunch"}
                ),
            )
            for kind in ("nutrition_analysis", "nutrition_record_draft")
        ]
    )
    planner = AgentRequestPlanner(
        resolver=SimpleNamespace(resolve=AsyncMock(return_value=[image])),
        intent_router=SimpleNamespace(route=AsyncMock(return_value=plan)),
        context_assembler=SimpleNamespace(load_memories=AsyncMock(return_value=[])),
    )
    planned = await planner.plan(
        user_id=original.user_id,
        request=AgentChatRequest(
            message="这是昨天中午吃的",
            image_asset_ids=[image.asset_id],
            context_hints=AgentContextHints(occurred_at=datetime(2026, 10, 17, 2, 14, tzinfo=UTC)),
        ),
        conversation_context=AgentConversationContext(),
    )
    executor = AgentBranchExecutor(
        {
            "nutrition_analysis": NutritionAnalysisBranchHandler(vision),
            "nutrition_record_draft": record_handler,
        }
    )
    result = await executor.execute(
        user_id=original.user_id, message="这是昨天中午吃的", planned_request=planned
    )
    result = AgentExecutionSafetyValidator().validate(result)
    analysis, record = result.branch_results
    assert analysis.status == record.status == "completed"
    assert not analysis.requires_confirmation and not analysis.confirmation_cards
    assert analysis.result["calculation"]["requires_confirmation"]
    assert record.requires_confirmation and len(record.confirmation_cards) == 1
    vision.analyze.assert_awaited_once()
    nutrition.propose_entry.assert_awaited_once()
    body = nutrition.propose_entry.call_args.kwargs["body"]
    assert body.meal_type == "lunch" and body.eaten_at.isoformat() == "2026-10-16T12:00:00+08:00"
    assert "12:00" in body.notes and "暂按" in body.notes
    assert "用油" in body.items[0].estimate_assumptions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters,expected",
    [
        ({"date": "2026-10-16", "meal_type": "dinner"}, "2026-10-16T19:00:00+08:00"),
        (
            {"date": "2026-10-16", "meal_type": "lunch", "eaten_time": "12:35"},
            "2026-10-16T12:35:00+08:00",
        ),
        (
            {"date": "2026-10-16", "meal_type": "lunch", "eaten_at": "2026-10-16T04:20:00Z"},
            "2026-10-16T04:20:00+00:00",
        ),
    ],
)
async def test_structured_meal_metadata_overrides_upload_time_and_generic_hints(
    parameters, expected
):
    branch = make_input()
    branch = replace(
        branch,
        task=branch.task.model_copy(update={"task_update": AgentTaskUpdate(parameters=parameters)}),
    )
    handler, vision, nutrition = make_handler()
    vision.analyze.return_value = estimated_analysis()
    nutrition.propose_entry.return_value = proposed_card()
    result = await handler.execute(branch)
    assert result.status == "completed"
    body = nutrition.propose_entry.call_args.kwargs["body"]
    assert body.meal_type == parameters["meal_type"] and body.eaten_at.isoformat() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters",
    [
        {"date": "not-a-date"},
        {"date": "2026-10-16", "eaten_at": "2026-10-17T12:00:00+08:00"},
        {"eaten_at": "2026-10-16T12:00:00"},
        {"date": "2026-10-16", "eaten_time": "invalid"},
    ],
)
async def test_invalid_or_conflicting_explicit_date_never_falls_back_to_upload_date(parameters):
    branch = make_input()
    branch = replace(
        branch,
        task=branch.task.model_copy(update={"task_update": AgentTaskUpdate(parameters=parameters)}),
    )
    handler, vision, nutrition = make_handler()
    vision.analyze.return_value = estimated_analysis()
    result = await handler.execute(branch)
    assert result.status == "needs_input" and "eaten_at" in result.missing_fields
    nutrition.propose_entry.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_primary_vision_is_preserved_and_not_implicitly_called_a_second_time():
    branch = make_input()
    error = AgentBranchError(code="VISION_MODEL_BUSY", message="视觉服务繁忙", retryable=True)
    branch = replace(
        branch,
        prior_results=(
            AgentBranchResult(
                task_type="nutrition_analysis",
                asset_ids=branch.task.asset_ids,
                status="failed",
                error=error,
            ),
        ),
    )
    handler, vision, nutrition = make_handler()
    result = await handler.execute(branch)
    assert result.status == "failed" and result.error == error
    vision.analyze.assert_not_awaited()
    nutrition.propose_entry.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_amount", [False, True])
async def test_known_photo_portions_are_estimable_but_explicit_invalid_values_are_not(
    invalid_amount,
):
    branch = make_input()
    update = AgentTaskUpdate(parameters={"amount_g": -1} if invalid_amount else {})
    branch = replace(
        branch,
        task=branch.task.model_copy(
            update={"task_update": update, "missing_fields": ["food_images", "amount_g", "kcal"]}
        ),
    )
    handler, vision, nutrition = make_handler()
    vision.analyze.return_value = estimated_analysis()
    nutrition.propose_entry.return_value = proposed_card()
    result = await handler.execute(branch)
    if invalid_amount:
        assert result.status == "needs_input" and "amount_g" in result.missing_fields
        nutrition.propose_entry.assert_not_awaited()
    else:
        assert result.status == "completed" and result.requires_confirmation
