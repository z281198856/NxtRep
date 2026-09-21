from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.training import (
    build_training_draft_tools,
    build_training_read_tools,
)
from nxtrep_backend.services.training import TrainingService


def make_context() -> MagicMock:
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    context.training_service = MagicMock(spec=TrainingService)
    context.training_service.get_active_plan = AsyncMock()
    context.training_service.list_calendar = AsyncMock()
    context.training_service.create_manual_draft = AsyncMock()
    context.training_service.submit_draft = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_read_active_training_plan_handles_missing_plan() -> None:
    context = make_context()
    context.training_service.get_active_plan.return_value = None
    current_tool = build_training_read_tools(context)[0]

    result = await current_tool.ainvoke({})

    assert result["status"] == "not_configured"
    context.training_service.get_active_plan.assert_awaited_once_with(user_id=context.user_id)


@pytest.mark.asyncio
async def test_propose_training_plan_creates_confirmation() -> None:
    context = make_context()
    exercise_id = uuid4()
    draft = SimpleNamespace(
        id=uuid4(),
        name="三日力量计划",
        status="editing",
        version=1,
        weekly_frequency=1,
        days=[],
        validation_errors=[],
        validation_warnings=[],
    )
    confirmation = SimpleNamespace(
        id=uuid4(),
        operation_type="training_plan_activate",
        status="pending",
        before=None,
        after={"plan_draft_id": str(draft.id)},
        impact="activate plan",
        expires_at=None,
        version=1,
    )
    context.training_service.create_manual_draft.return_value = draft
    context.training_service.submit_draft.return_value = confirmation
    current_tool = next(
        item for item in build_training_draft_tools(context) if item.name == "propose_training_plan"
    )

    result = await current_tool.ainvoke(
        {
            "name": "三日力量计划",
            "weekly_frequency": 1,
            "days": [
                {
                    "day_index": 1,
                    "name": "全身训练",
                    "estimated_minutes": 60,
                    "exercises": [
                        {
                            "exercise_id": str(exercise_id),
                            "order_no": 1,
                            "target_sets": 3,
                            "rep_min": 8,
                            "rep_max": 12,
                        }
                    ],
                }
            ],
        }
    )

    assert result["status"] == "confirmation_required"
    assert result["confirmation"]["operation_type"] == "training_plan_activate"
    body = context.training_service.create_manual_draft.await_args.args[1]
    assert body.days[0].exercises[0].exercise_id == exercise_id
    context.training_service.submit_draft.assert_awaited_once_with(
        context.user_id,
        draft.id,
        draft.version,
    )
