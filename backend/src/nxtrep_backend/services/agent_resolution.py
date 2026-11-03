"""Classify execution feedback for one bounded continuation in the existing Agent."""

import re

from nxtrep_backend.schemas.agent import AgentBranchResult, AgentIntentTask
from nxtrep_backend.services.agent_context_builder import bound_payload
from nxtrep_backend.services.agent_personal_context import OPTIONAL_DRAFT_FIELDS

_STOP_CODES = (
    "AUTH", "PERMISSION", "ACCESS_DENIED", "TIMEOUT", "OUTCOME_UNKNOWN",
    "INTERRUPTED", "RESULT_INVALID", "RATE_LIMIT", "DEPENDENCY", "CALL_LIMIT",
    "NO_PROGRESS", "LOOP",
)
_SIDE_EFFECT_STATUSES = {"confirmation_required", "saved", "updated", "deleted", "cancelled"}


def resolution_feedback(result: AgentBranchResult, task: AgentIntentTask) -> dict | None:
    """An unresolved lookup is feedback, not a new user instruction or a retry grant."""
    if (
        result.status != "needs_input" or result.operation_results
        or result.confirmation_cards or result.requires_confirmation
        or task.task_update and task.task_update.invalid_fields
    ):
        return None
    payloads = (result.result or {}).get("task_tool_results") or []
    if not payloads or not all(isinstance(item, dict) for item in payloads):
        return None
    if any(
        item.get("status") in _SIDE_EFFECT_STATUSES
        or any(part in str(item.get("error_code", "")).upper() for part in _STOP_CODES)
        for item in payloads
    ):
        return None
    if not any(item.get("status") in {"needs_input", "needs_review"} for item in payloads):
        return None
    return bound_payload({
        "task_type": task.task_type,
        "missing_fields": result.missing_fields,
        "tool_results": payloads,
        "previous_reply": (result.result or {}).get("task_answer"),
    }, 6000)


def blocking_input_fields(task: AgentIntentTask, fields: list[str]) -> list[str]:
    """Keep absent real facts strict; IDs, versions and search filters can be resolved."""
    hard = set(task.task_update.invalid_fields if task.task_update else ())
    hard.update({"injury_clearance", "medical_clearance"})
    hard.update(field for field in fields if re.fullmatch(r"items\[\d+\]\.amount_g", field))
    if task.task_type == "workout_record_draft":
        hard.update({"weight_kg", "sets", "reps", "exercise_name"})
    if task.task_type in {
        "nutrition_record_draft", "food_catalog_draft", "general_question", "knowledge_retrieval",
    } and not (task.task_update and task.task_update.entities):
        hard.update({"food_name", "food_details", "identifiable_food", "items"})
        if any(field in fields for field in hard):
            hard.update({"amount_g", "nutrients"})
    if task.task_type in {"general_question", "knowledge_retrieval"} and (
        task.task_update and task.task_update.entities
    ):
        # Saved quantities must come from a real read, never a generic estimate.
        hard.update({"amount_g", "nutrients"})
    return [field for field in fields if field in hard]


def observation_input_fields(task: AgentIntentTask, fields: list[str], resolved=()) -> list[str]:
    """A validated observation resolves its inputs; optional profile gaps do not block it."""
    invalid = set(task.task_update.invalid_fields if task.task_update else ())
    optional = OPTIONAL_DRAFT_FIELDS | {"training_goal"} | set(resolved)
    return [field for field in dict.fromkeys([*fields, *invalid])
            if field in invalid or field not in optional]
