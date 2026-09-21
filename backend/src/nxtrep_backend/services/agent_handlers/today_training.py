from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nxtrep_backend.agents.intent_router import is_today_training_query
from nxtrep_backend.agents.tools.common import json_safe
from nxtrep_backend.schemas.agent import AgentBranchResult
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutNotFoundError, WorkoutService

DEFAULT_TIMEZONE = "Asia/Shanghai"


def _current_date(timezone_name: str | None) -> date:
    try:
        timezone = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(timezone).date()


class TodayTrainingQueryBranchHandler:
    """Fast path for the home-screen "today's workout" prompt."""

    def __init__(
        self,
        training_service: TrainingService,
        workout_service: WorkoutService,
        fallback: GeneralQuestionBranchHandler,
        *,
        today_provider: Callable[[str | None], date] = _current_date,
    ) -> None:
        self._training_service = training_service
        self._workout_service = workout_service
        self._fallback = fallback
        self._today_provider = today_provider

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        task = branch_input.task
        if task.task_type != "structured_data_query":
            raise ValueError(
                "TodayTrainingQueryBranchHandler requires a structured_data_query task"
            )
        if not is_today_training_query(branch_input.message):
            return await self._fallback.execute(branch_input)

        today = self._today_provider(branch_input.context_hints.timezone)
        active_plan = await self._training_service.get_active_plan(
            user_id=branch_input.user_id,
        )
        events = await self._training_service.list_calendar(
            user_id=branch_input.user_id,
            start_date=today,
            end_date=today,
        )
        try:
            active_workout = await self._workout_service.get_active(branch_input.user_id)
        except WorkoutNotFoundError:
            active_workout = None

        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status="completed",
            result={
                "query_kind": "today_training",
                "date": today.isoformat(),
                "active_plan": (
                    {
                        "version_id": str(active_plan.id),
                        "plan_id": str(active_plan.plan_id),
                        "name": active_plan.name,
                        "weekly_frequency": active_plan.weekly_frequency,
                        "days": json_safe(active_plan.days),
                    }
                    if active_plan is not None
                    else None
                ),
                "scheduled_events": [
                    {
                        "id": str(item.id),
                        "status": item.status,
                        "title": item.title,
                        "estimated_minutes": item.estimated_minutes,
                        "actual_workout_id": (
                            str(item.actual_workout_id) if item.actual_workout_id else None
                        ),
                        "content": json_safe(item.content_snapshot),
                    }
                    for item in events
                ],
                "active_workout": self._active_workout_payload(active_workout),
            },
        )

    @staticmethod
    def _active_workout_payload(active_workout: object | None) -> dict | None:
        if active_workout is None:
            return None
        workout = active_workout.workout
        return {
            "id": str(workout.id),
            "status": workout.status,
            "started_at": workout.started_at.isoformat(),
            "exercises": [
                {
                    "name": item.name_snapshot,
                    "target": json_safe(item.target_snapshot),
                    "completed_sets": len(active_workout.sets_by_exercise.get(item.id, [])),
                }
                for item in active_workout.exercises
            ],
        }
