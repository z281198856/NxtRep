from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.repositories.workout import WorkoutAggregate
from nxtrep_backend.schemas.workout import (
    ProgressionDraftCreateRequest,
    WorkoutSetCorrectionRequest,
    WorkoutSetVoidRequest,
)
from nxtrep_backend.services.workout import WorkoutConflictError, WorkoutNotFoundError


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
                        "id": str(workout_set.id),
                        "version": workout_set.version,
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
    async def read_recent_workouts(
        days: int = 14,
        start_date: date | None = None,
        end_date: date | None = None,
        period: Literal["this_week", "last_week"] | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> dict:
        """Read workouts. Use period=this_week or last_week for calendar weeks (Monday start)."""
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            return {"status": "invalid_request", "message": "无法识别查询时区，请核对时区。"}
        today = datetime.now(zone).date()
        if period is not None:
            if start_date is not None or end_date is not None:
                return {"status": "invalid_request", "message": "周区间与自定义日期只能选择一种。"}
            monday = today - timedelta(days=today.weekday())
            start_date = monday if period == "this_week" else monday - timedelta(days=7)
            end_date = today if period == "this_week" else monday - timedelta(days=1)
        safe_days = min(max(days, 1), 90)
        end_date = end_date or today
        start_date = start_date or end_date - timedelta(days=safe_days - 1)
        if start_date > end_date or (end_date - start_date).days > 89:
            return {"status": "invalid_request", "message": "训练查询范围须为 1 至 90 天。"}
        safe_days = (end_date - start_date).days + 1
        history = await context.workout_service.list_history(
            user_id=context.user_id,
            start_date=start_date,
            end_date=end_date,
            status=None,
            page=1,
            page_size=100,
            timezone=timezone,
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
        if not draft.suggestions:
            return {
                "status": "needs_review",
                "draft": {
                    "id": str(draft.id),
                    "suggestions": [],
                    "warnings": ["没有可用于递增的有效训练组，请先完成并记录训练。"],
                },
                "confirmation": None,
            }
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


def build_workout_correction_tools(context: AgentToolContext) -> list[BaseTool]:
    read_versions: dict[tuple[UUID, UUID], int] = {}
    proposals: dict[str, dict] = {}

    @tool
    async def read_workout_set_for_change(
        exercise_name: str,
        set_index: int | None = None,
        workout_date: date | None = None,
        workout_id: UUID | None = None,
    ) -> dict:
        """Locate owned sets by workout/date, exercise and group; ask on ambiguity."""
        if workout_id is None and workout_date is None:
            return {"status": "needs_review", "message": "请先确定是哪一天或哪次训练的记录。"}
        if not exercise_name.strip() or (set_index is not None and set_index < 1):
            return {"status": "needs_review", "message": "请核对动作名称和训练组数。"}
        if workout_id is None:
            history = await context.workout_service.list_history(
                user_id=context.user_id,
                start_date=workout_date,
                end_date=workout_date,
                status=None,
                page=1,
                page_size=20,
                timezone="Asia/Shanghai",
            )
            if history.has_more:
                return {"status": "needs_review", "message": "当天有多次训练，请先明确哪次训练。"}
            workout_ids = [item.id for item in history.list]
        else:
            workout_ids = [workout_id]
        candidates = []
        keyword = "".join(exercise_name.casefold().split())
        for identifier in workout_ids:
            try:
                aggregate = await context.workout_service.get_aggregate(context.user_id, identifier)
            except WorkoutNotFoundError:
                continue
            local_date = aggregate.workout.started_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
            if workout_date is not None and local_date != workout_date:
                continue
            for exercise in aggregate.exercises:
                normalized = "".join(exercise.name_snapshot.casefold().split())
                if keyword not in normalized:
                    continue
                for item in aggregate.sets_by_exercise.get(exercise.id, []):
                    if set_index is not None and item.set_index != set_index:
                        continue
                    candidates.append(
                        {
                            "workout_id": str(identifier),
                            "set_id": str(item.id),
                            "version": item.version,
                            "date": local_date.isoformat(),
                            "exercise_name": exercise.name_snapshot,
                            "set_index": item.set_index,
                            "weight_kg": str(item.weight_kg),
                            "reps": item.reps,
                        }
                    )
        exact = [
            item
            for item in candidates
            if "".join(item["exercise_name"].casefold().split()) == keyword
        ]
        candidates = exact or candidates
        if len(candidates) != 1:
            return {
                "status": "needs_review",
                "candidates": candidates,
                "message": "有多个可能的训练组，请选择具体动作、训练或第几组。"
                if candidates
                else "未找到对应有效训练组，请核对日期、动作及组数。",
            }
        selected = candidates[0]
        read_versions[(UUID(selected["workout_id"]), UUID(selected["set_id"]))] = selected[
            "version"
        ]
        return {"status": "available", "selected_set": selected}

    async def propose(workout_id, set_id, body):
        if read_versions.get((workout_id, set_id)) != body.expected_version:
            return {"status": "needs_review", "message": "请先读取并核对该训练组的最新内容。"}
        key = f"{type(body).__name__}:{workout_id}:{set_id}:" + body.model_dump_json(
            exclude_unset=True
        )
        if key in proposals:
            return proposals[key]
        try:
            confirmation = await context.workout_service.propose_set_change(
                context.user_id, workout_id, set_id, body
            )
        except (WorkoutNotFoundError, WorkoutConflictError):
            return {
                "status": "needs_review",
                "message": "记录不存在、已作废或版本变化，请重新读取核对。",
            }
        payload = {
            "status": "confirmation_required",
            "confirmation": confirmation_payload(confirmation),
        }
        proposals[key] = payload
        return payload

    @tool
    async def propose_workout_set_update(
        workout_id: UUID, set_id: UUID, changes: WorkoutSetCorrectionRequest
    ) -> dict:
        """Draft a read and selected recorded set's weight/reps correction; approval required."""
        return await propose(workout_id, set_id, changes)

    @tool
    async def propose_workout_set_void(
        workout_id: UUID, set_id: UUID, request: WorkoutSetVoidRequest
    ) -> dict:
        """Draft voiding one selected mistaken set; preserve history and require approval."""
        return await propose(workout_id, set_id, request)

    return [read_workout_set_for_change, propose_workout_set_update, propose_workout_set_void]
