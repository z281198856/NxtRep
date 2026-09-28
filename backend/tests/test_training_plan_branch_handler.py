import json
from decimal import Decimal
from types import SimpleNamespace
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
)
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError


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

    result = await TrainingPlanBranchHandler(react).execute(make_input())

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "TRAINING_PLAN_DRAFT_NOT_CREATED"


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


@pytest.mark.asyncio
async def test_training_plan_includes_verified_personal_context_without_inventing_data() -> None:
    exercise_id = uuid4()
    card = AgentConfirmationCard(
        confirmation_id=uuid4(),
        operation_type="training_plan_activate",
        status="pending",
        impact="激活训练计划",
        expires_at="2026-09-29T00:00:00+08:00",
        version=1,
    )
    react = MagicMock(spec=GeneralQuestionBranchHandler)
    react.execute = AsyncMock(
        return_value=AgentBranchResult(
            task_type="training_plan_draft",
            status="completed",
            result={"answer": "草稿已创建"},
            operation_results=[
                {
                    "status": "confirmation_required",
                    "draft": {
                        "name": "三日计划",
                        "days": [
                            {
                                "name": "全身 A",
                                "exercises": [{"exercise_id": str(exercise_id)}],
                            }
                        ],
                    },
                }
            ],
            confirmation_cards=[card],
            requires_confirmation=True,
        )
    )
    tools = MagicMock()
    tools.profile_service.get_profile = AsyncMock(
        return_value=SimpleNamespace(
            height_cm=Decimal("178"),
            experience_level="beginner",
            weekly_training_days=3,
            session_duration_minutes=45,
        )
    )
    tools.goals_service.get_goals_and_constraints = AsyncMock(
        return_value=SimpleNamespace(goal=SimpleNamespace(goal_type="fat_loss_retain"))
    )
    tools.body_service.recent_measurement_summary = AsyncMock(
        return_value={
            "weight_kg": "78.5",
            "weight_recorded_at": "2026-09-20",
            "body_fat_percent": "24.0",
            "body_fat_recorded_at": "2026-09-20",
        }
    )
    tools.training_service.repository.plan_exercise_names = AsyncMock(
        return_value={str(exercise_id): "哑铃卧推"}
    )

    result = await TrainingPlanBranchHandler(react, tools).execute(make_input())

    sent = react.execute.await_args.args[0]
    payload = json.loads(sent.message)
    assert payload["current_user_message"] == "帮我制定训练计划"
    assert payload["verified_user_context"]["profile"]["height_cm"] == "178"
    assert result.result["personal_context"]["goal_type"] == "fat_loss_retain"
    assert result.result["personal_context"]["measurements"]["body_fat_percent"] == "24.0"
    assert (
        result.operation_results[0]["draft"]["days"][0]["exercises"][0]["exercise_name"]
        == "哑铃卧推"
    )
    tools.training_service.repository.plan_exercise_names.assert_awaited_once_with(
        sent.user_id, {exercise_id}
    )


@pytest.mark.asyncio
async def test_training_plan_marks_missing_profile_and_body_data_as_missing() -> None:
    react = MagicMock(spec=GeneralQuestionBranchHandler)
    react.execute = AsyncMock(
        return_value=AgentBranchResult(
            task_type="training_plan_draft",
            status="needs_input",
            missing_fields=["goal_type"],
        )
    )
    tools = MagicMock()
    tools.profile_service.get_profile = AsyncMock(side_effect=ProfileNotFoundError())
    tools.goals_service.get_goals_and_constraints = AsyncMock(
        side_effect=GoalsNotFoundError()
    )
    tools.body_service.recent_measurement_summary = AsyncMock(
        return_value={"weight_kg": None, "body_fat_percent": None}
    )

    result = await TrainingPlanBranchHandler(react, tools).execute(make_input())

    assert result.status == "needs_input"
    assert "personal_context" not in (result.result or {})
    payload = json.loads(react.execute.await_args.args[0].message)
    assert "profile" not in payload["verified_user_context"]
    assert payload["verified_user_context"]["measurements"]["weight_kg"] is None
