from datetime import date
from typing import Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.training import (
    PlanDayInput,
    PlanDraftCreateRequest,
    RescheduleDraftCreateRequest,
)


def build_training_read_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_active_training_plan() -> dict:
        """Read the user's currently active training plan and its days."""
        plan = await context.training_service.get_active_plan(
            user_id=context.user_id,
        )
        if plan is None:
            return {
                "status": "not_configured",
                "message": "The user has no active training plan.",
            }
        return {
            "status": "available",
            "plan": {
                "version_id": str(plan.id),
                "plan_id": str(plan.plan_id),
                "name": plan.name,
                "version": plan.version,
                "weekly_frequency": plan.weekly_frequency,
                "days": json_safe(plan.days),
                "activated_at": plan.activated_at.isoformat(),
            },
        }

    @tool
    async def read_calendar(start_date: date, end_date: date) -> dict:
        """Read scheduled workouts in an inclusive date range of at most 92 days."""
        if start_date > end_date:
            return {
                "status": "invalid_request",
                "message": "start_date must not exceed end_date.",
            }
        if (end_date - start_date).days > 91:
            return {
                "status": "invalid_request",
                "message": "The calendar range must not exceed 92 days.",
            }
        events = await context.training_service.list_calendar(
            user_id=context.user_id,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "status": "available",
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "events": [
                {
                    "id": str(item.id),
                    "scheduled_date": item.scheduled_date.isoformat(),
                    "status": item.status,
                    "plan_day_id": (str(item.plan_day_id) if item.plan_day_id else None),
                    "title": item.title,
                    "estimated_minutes": item.estimated_minutes,
                    "actual_workout_id": (
                        str(item.actual_workout_id) if item.actual_workout_id else None
                    ),
                }
                for item in events
            ],
        }

    return [read_active_training_plan, read_calendar]


def build_training_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def propose_training_plan(
        name: str,
        weekly_frequency: int,
        days: list[PlanDayInput],
    ) -> dict:
        """Create and validate a training plan proposal for user confirmation."""
        draft = await context.training_service.create_manual_draft(
            context.user_id,
            PlanDraftCreateRequest(
                name=name,
                weekly_frequency=weekly_frequency,
                days=days,
            ),
        )
        draft_result = {
            "id": str(draft.id),
            "name": draft.name,
            "status": draft.status,
            "version": draft.version,
            "weekly_frequency": draft.weekly_frequency,
            "days": json_safe(draft.days),
            "validation_errors": draft.validation_errors,
            "validation_warnings": draft.validation_warnings,
        }
        if draft.validation_errors:
            return {
                "status": "needs_review",
                "draft": draft_result,
                "confirmation": None,
            }
        confirmation = await context.training_service.submit_draft(
            context.user_id,
            draft.id,
            draft.version,
        )
        draft_result["version"] = draft.version
        draft_result["status"] = draft.status
        return {
            "status": "confirmation_required",
            "draft": draft_result,
            "confirmation": confirmation_payload(confirmation),
        }

    @tool
    async def propose_schedule_change(
        missed_event_id: UUID,
        strategy: Literal["shift", "merge", "skip"],
        target_date: date | None = None,
        reason: str | None = None,
    ) -> dict:
        """Propose shifting, merging, or skipping a missed workout."""
        draft = await context.training_service.create_reschedule_draft(
            context.user_id,
            RescheduleDraftCreateRequest(
                missed_event_id=missed_event_id,
                strategy=strategy,
                target_date=target_date,
                reason=reason,
            ),
        )
        draft_result = {
            "id": str(draft.id),
            "status": draft.status,
            "version": draft.version,
            "strategy": draft.strategy,
            "before_events": json_safe(draft.before_events),
            "after_events": json_safe(draft.after_events),
            "duration_change_minutes": draft.duration_change_minutes,
            "volume_change_percent": str(draft.volume_change_percent),
            "warnings": draft.warnings,
        }
        if draft.warnings:
            return {
                "status": "needs_review",
                "draft": draft_result,
                "confirmation": None,
            }
        confirmation = await context.training_service.submit_reschedule(
            context.user_id,
            draft.id,
            draft.version,
        )
        draft_result["version"] = draft.version
        draft_result["status"] = draft.status
        return {
            "status": "confirmation_required",
            "draft": draft_result,
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_training_plan, propose_schedule_change]
