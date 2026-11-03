"""Recover a task's proposal only from matching, owned execution evidence."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.db.models import AgentRun, Confirmation
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskCandidate, clean_entities
from nxtrep_backend.services.agent_task_state import TaskStateManager

TASK_OPERATIONS = {
    "workout_record_draft": {"workout_record_create"},
    "workout_record_update_draft": {"workout_record_update"},
    "workout_record_void_draft": {"workout_record_void"},
    "workout_set_update_draft": {"workout_set_update"},
    "workout_set_void_draft": {"workout_set_void"},
    "nutrition_record_draft": {"nutrition_entry_create"},
    "nutrition_entry_update_draft": {"nutrition_entry_update", "nutrition_entries_date_change"},
    "nutrition_entry_delete_draft": {"nutrition_entry_delete", "nutrition_entry_update"},
    "profile_update_draft": {"profile_update"},
    "training_plan_draft": {"training_plan_activate"},
    "schedule_change_draft": {"calendar_reschedule"},
    "training_progression_draft": {"training_progression_apply"},
    "nutrition_target_draft": {"nutrition_target_activate"},
    "body_measurement_draft": {"body_measurement_create"},
    "water_record_draft": {"water_entry_create"},
    "food_catalog_draft": {"food_create", "food_update", "food_delete"},
}


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _entries(checkpoint: dict, name: str) -> list:
    value = checkpoint.get(name)
    return value if isinstance(value, list) else []


async def recover_task_confirmation(
    session: AsyncSession,
    user_id: UUID,
    conversation_id: UUID,
    task: AgentTask,
) -> AgentTask | None:
    """Return a verified task copy, or None when no reliable association exists.

    A recent card or matching operation type is insufficient. The proposal needs
    all four links: owned conversation run -> exact task ID -> exact tool call ID
    -> returned confirmation reference, followed by a current owned DB read.
    """
    permitted = TASK_OPERATIONS.get(task.task_type)
    if not permitted:
        return None
    checkpoints = list(
        await session.scalars(
            select(AgentRun.checkpoint)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.conversation_id == conversation_id,
                AgentRun.checkpoint["tool_runs"].contains([{"task_id": str(task.task_id)}]),
            )
            .order_by(AgentRun.created_at.desc())
            .limit(100)
        )
    )
    identifiers = set()
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict):
            continue
        records = {
            str(record["tool_call_id"]): record
            for record in _entries(checkpoint, "tool_runs")
            if isinstance(record, dict)
            and record.get("tool_call_id")
            and record.get("task_id") == str(task.task_id)
            and record.get("status") == "confirmation_required"
            and str(record.get("tool_name", "")).startswith("propose_")
        }
        returned = {_uuid(identifier) for identifier in _entries(checkpoint, "confirmation_refs")}
        for operation in _entries(checkpoint, "operations"):
            if (
                not isinstance(operation, dict)
                or operation.get("status") != "confirmation_required"
            ):
                continue
            record = records.get(str(operation.get("tool_call_id")))
            if not record or record.get("tool_name") != operation.get("tool_name"):
                continue
            identifier = _uuid(operation.get("confirmation_id"))
            if identifier is not None and identifier in returned:
                identifiers.add(identifier)
    if not identifiers:
        return None
    now = datetime.now(UTC)
    cards = list(
        await session.scalars(
            select(Confirmation)
            .where(
                Confirmation.user_id == user_id,
                Confirmation.id.in_(identifiers),
                Confirmation.operation_type.in_(permitted),
                Confirmation.status.in_({"pending", "succeeded"}),
            )
            .order_by(Confirmation.created_at, Confirmation.id)
        )
    )
    cards = [card for card in cards if card.status == "succeeded" or card.expires_at > now]
    if not cards:
        return None
    if len(cards) > 1:
        recovered = task.model_copy(deep=True)
        recovered.status, recovered.current_step = "collecting", "clarify_target"
        recovered.missing_fields = list(dict.fromkeys([*recovered.missing_fields, "selection"]))
        recovered.candidates = [
            AgentTaskCandidate(
                kind="confirmation",
                id=card.id,
                label=f"第{index}份草稿：{card.impact[:100]}",
            )
            for index, card in enumerate(cards[:20], 1)
        ]
        recovered.last_tool_result = {"status": "needs_review", "reason": "multiple_task_proposals"}
        return recovered
    card = cards[0]
    recovered = TaskStateManager.commit_results(
        {"active_task": task.model_dump(mode="json")},
        tool_results=[card.result] if isinstance(card.result, dict) else [],
        confirmation_cards=[confirmation_payload(card)],
    ).active_task
    if recovered is not None and isinstance(card.result, dict):
        resource = card.result.get("resource_id")
        if resource and card.operation_type.startswith("nutrition_entry_"):
            recovered.entities = clean_entities({**recovered.entities, "entry_id": resource})
    return recovered
