from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentConfirmationCard,
    AgentIntentTask,
)
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_handlers.training_plan import (
    TrainingPlanBranchHandler,
    TrainingPlanWorkflowError,
)


def make_input() -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message="帮我制定训练计划",
        task=AgentIntentTask(
            task_type="training_plan_draft",
            confidence="high",
            routing_reason="create plan",
        ),
        images=(),
    )


@pytest.mark.asyncio
async def test_training_workflow_requires_activation_confirmation() -> None:
    react = MagicMock(spec=GeneralQuestionBranchHandler)
    react.execute = AsyncMock(
        return_value=AgentBranchResult(
            task_type="training_plan_draft",
            status="completed",
            result={"answer": "draft ready"},
        )
    )

    with pytest.raises(TrainingPlanWorkflowError, match="confirmation draft"):
        await TrainingPlanBranchHandler(react).execute(make_input())


@pytest.mark.asyncio
async def test_training_workflow_accepts_validated_activation_draft() -> None:
    card = AgentConfirmationCard(
        confirmation_id=uuid4(),
        operation_type="training_plan_activate",
        status="pending",
        impact="激活训练计划",
        expires_at="2026-09-09T00:00:00+08:00",
        version=1,
    )
    expected = AgentBranchResult(
        task_type="training_plan_draft",
        status="completed",
        result={"answer": "draft ready"},
        confirmation_cards=[card],
        requires_confirmation=True,
    )
    react = MagicMock(spec=GeneralQuestionBranchHandler)
    react.execute = AsyncMock(return_value=expected)

    assert await TrainingPlanBranchHandler(react).execute(make_input()) == expected
