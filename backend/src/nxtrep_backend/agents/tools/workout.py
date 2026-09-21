from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.repositories.workout import WorkoutAggregate
from nxtrep_backend.schemas.workout import ProgressionDraftCreateRequest
from nxtrep_backend.services.workout import WorkoutNotFoundError


def _aggregate_payload(aggregate: WorkoutAggregate) -> dict:
    workout = aggregate.workout
    return {
        "id": str(workout.id),
        "status": workout.status,
        "started_at": workout.started_at.isoformat(),
        "ended_at": workout.ended_at.isoformat() if workout.ended_at else None,
        "version": workout.version,
        "pre_check": json_safe(workout.pre_check),
        "overall_difficulty": workout.overall_difficulty,
        "fatigue": workout.fatigue,
        "pain": workout.pain,
        "interruption_reason": workout.interruption_reason,
        "exercises": [
            {
                "item_id": str(item.id),
                "exercise_id": str(item.exercise_id) if item.exercise_id else None,
                "name": item.name_snapshot,
                "target": json_safe(item.target_snapshot),
                "sets": [
                    {
                        "set_index": workout_set.set_index,
                        "weight_kg": str(workout_set.weight_kg),
                        "reps": workout_set.reps,
                        "rir": workout_set.rir,
                        "rpe": (str(workout_set.rpe) if workout_set.rpe is not None else None),
                        "tags": workout_set.tags,
                        "completed_at": workout_set.completed_at.isoformat(),
                    }
                    for workout_set in aggregate.sets_by_exercise.get(item.id, [])
                ],
            }
            for item in aggregate.exercises
        ],
    }


def build_workout_read_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_recent_workouts(days: int = 14) -> dict:
        """Read a summary of the current user's recent workouts."""
        safe_days = min(max(days, 1), 90)
        end_date = datetime.now(CHINA_TIMEZONE).date()
        start_date = end_date - timedelta(days=safe_days - 1)
        history = await context.workout_service.list_history(
            user_id=context.user_id,
            start_date=start_date,
            end_date=end_date,
            status=None,
            page=1,
            page_size=100,
        )
        total_sets = sum(item.completed_sets for item in history.list)
        total_volume = sum(
            (item.total_volume_kg for item in history.list),
            Decimal("0"),
        )
        return {
            "status": "available",
            "period": {
                "days": safe_days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "summary": {
                "workout_count": history.total,
                "returned_count": len(history.list),
                "completed_workout_count": sum(item.status == "completed" for item in history.list),
                "completed_sets": total_sets,
                "total_volume_kg": str(total_volume),
                "total_duration_seconds": sum(item.duration_seconds or 0 for item in history.list),
                "personal_record_count": sum(item.pr_count for item in history.list),
                "has_more": history.has_more,
            },
            "workouts": [
                {
                    "id": str(item.id),
                    "date": item.date.isoformat(),
                    "status": item.status,
                    "duration_seconds": item.duration_seconds,
                    "completed_sets": item.completed_sets,
                    "total_volume_kg": str(item.total_volume_kg),
                    "personal_record_count": item.pr_count,
                }
                for item in history.list
            ],
        }

    @tool
    async def read_active_workout() -> dict:
        """Read the current user's unfinished workout with its recorded sets."""
        try:
            aggregate = await context.workout_service.get_active(context.user_id)
        except WorkoutNotFoundError:
            return {"status": "not_found", "message": "No active workout."}
        return {"status": "available", "workout": _aggregate_payload(aggregate)}

    @tool
    async def read_workout_detail(workout_id: UUID) -> dict:
        """Read one workout and all of its exercises and recorded sets."""
        try:
            aggregate = await context.workout_service.get_aggregate(
                context.user_id,
                workout_id,
            )
        except WorkoutNotFoundError:
            return {"status": "not_found", "message": "Workout not found."}
        return {"status": "available", "workout": _aggregate_payload(aggregate)}

    @tool
    async def read_exercise_history(
        exercise_id: UUID,
        limit: int = 10,
    ) -> dict:
        """Read recent set performance for one exercise."""
        safe_limit = min(max(limit, 1), 20)
        try:
            entries = await context.workout_service.list_exercise_history(
                user_id=context.user_id,
                exercise_id=exercise_id,
                limit=safe_limit,
            )
        except WorkoutNotFoundError:
            return {"status": "not_found", "message": "Exercise not found."}
        return {
            "status": "available",
            "exercise_id": str(exercise_id),
            "sessions": [
                {
                    "workout_id": str(entry.workout.id),
                    "started_at": entry.workout.started_at.isoformat(),
                    "workout_status": entry.workout.status,
                    "exercise_name": entry.exercise.name_snapshot,
                    "target": json_safe(entry.exercise.target_snapshot),
                    "sets": [
                        {
                            "set_index": item.set_index,
                            "weight_kg": str(item.weight_kg),
                            "reps": item.reps,
                            "rir": item.rir,
                            "rpe": str(item.rpe) if item.rpe is not None else None,
                            "tags": item.tags,
                        }
                        for item in entry.sets
                    ],
                }
                for entry in entries
            ],
        }

    return [
        read_recent_workouts,
        read_active_workout,
        read_workout_detail,
        read_exercise_history,
    ]


def build_workout_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def propose_progression(
        workout_id: UUID,
        exercise_ids: list[UUID] | None = None,
    ) -> dict:
        """Propose conservative next-session progression for a finished workout."""
        draft = await context.workout_service.create_progression_draft(
            context.user_id,
            workout_id,
            ProgressionDraftCreateRequest(exercise_ids=exercise_ids),
        )
        confirmation = await context.workout_service.submit_progression(
            context.user_id,
            workout_id,
            draft.id,
            draft.version,
        )
        return {
            "status": "confirmation_required",
            "draft": {
                "id": str(draft.id),
                "version": draft.version,
                "status": draft.status,
                "suggestions": json_safe(draft.suggestions),
            },
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_progression]
