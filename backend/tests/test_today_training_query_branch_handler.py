from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentBranchResult, AgentIntentTask
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_handlers.today_training import (
    TodayTrainingQueryBranchHandler,
)
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutNotFoundError, WorkoutService

TODAY = date(2026, 9, 13)


def make_input(message: str) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message=message,
        task=AgentIntentTask(
            task_type="structured_data_query",
            required_context=["training_plan", "calendar", "workout"],
            confidence="high",
            routing_reason="today training fast path",
        ),
        images=(),
    )


@pytest.mark.asyncio
async def test_today_training_handler_reads_data_directly_without_react_agent() -> None:
    plan = SimpleNamespace(
        id=uuid4(),
        plan_id=uuid4(),
        name="两日训练",
        weekly_frequency=2,
        days=[{"name": "全身 A"}],
    )
    event = SimpleNamespace(
        id=uuid4(),
        status="planned",
        title="全身 A",
        estimated_minutes=45,
        actual_workout_id=None,
        content_snapshot={"exercises": [{"name": "深蹲"}]},
    )
    workout = SimpleNamespace(
        id=uuid4(),
        status="in_progress",
        started_at=datetime(2026, 9, 13, 8, 0),
    )
    exercise = SimpleNamespace(
        id=uuid4(),
        name_snapshot="深蹲",
        target_snapshot={"sets": 3},
    )
    aggregate = SimpleNamespace(
        workout=workout,
        exercises=[exercise],
        sets_by_exercise={exercise.id: [object()]},
    )
    training = MagicMock(spec=TrainingService)
    training.get_active_plan = AsyncMock(return_value=plan)
    training.list_calendar = AsyncMock(return_value=[event])
    workouts = MagicMock(spec=WorkoutService)
    workouts.get_active = AsyncMock(return_value=aggregate)
    fallback = MagicMock(spec=GeneralQuestionBranchHandler)
    fallback.execute = AsyncMock()
    handler = TodayTrainingQueryBranchHandler(
        training,
        workouts,
        fallback,
        today_provider=lambda _timezone: TODAY,
    )
    branch_input = make_input("今天怎么练？")

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert result.result["query_kind"] == "today_training"
    assert result.result["date"] == "2026-09-13"
    assert result.result["active_plan"]["name"] == "两日训练"
    assert result.result["scheduled_events"][0]["title"] == "全身 A"
    assert result.result["active_workout"]["exercises"][0]["completed_sets"] == 1
    training.get_active_plan.assert_awaited_once_with(user_id=branch_input.user_id)
    training.list_calendar.assert_awaited_once_with(
        user_id=branch_input.user_id,
        start_date=TODAY,
        end_date=TODAY,
    )
    workouts.get_active.assert_awaited_once_with(branch_input.user_id)
    fallback.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_today_training_handler_handles_no_active_workout() -> None:
    training = MagicMock(spec=TrainingService)
    training.get_active_plan = AsyncMock(return_value=None)
    training.list_calendar = AsyncMock(return_value=[])
    workouts = MagicMock(spec=WorkoutService)
    workouts.get_active = AsyncMock(side_effect=WorkoutNotFoundError("not found"))
    fallback = MagicMock(spec=GeneralQuestionBranchHandler)
    fallback.execute = AsyncMock()
    handler = TodayTrainingQueryBranchHandler(
        training,
        workouts,
        fallback,
        today_provider=lambda _timezone: TODAY,
    )

    result = await handler.execute(make_input("今天练什么？"))

    assert result.status == "completed"
    assert result.result["active_plan"] is None
    assert result.result["scheduled_events"] == []
    assert result.result["active_workout"] is None


@pytest.mark.asyncio
async def test_today_training_handler_delegates_other_structured_queries() -> None:
    training = MagicMock(spec=TrainingService)
    workouts = MagicMock(spec=WorkoutService)
    fallback_result = AgentBranchResult(
        task_type="structured_data_query",
        status="completed",
        result={"answer": "最近训练数据"},
    )
    fallback = MagicMock(spec=GeneralQuestionBranchHandler)
    fallback.execute = AsyncMock(return_value=fallback_result)
    handler = TodayTrainingQueryBranchHandler(training, workouts, fallback)
    branch_input = make_input("我最近练得怎么样？")

    result = await handler.execute(branch_input)

    assert result == fallback_result
    fallback.execute.assert_awaited_once_with(branch_input)
    training.get_active_plan.assert_not_called()
