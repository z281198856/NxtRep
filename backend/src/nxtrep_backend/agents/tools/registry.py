import asyncio
import json
import re
from collections.abc import Callable, Iterable
from functools import wraps
from inspect import signature
from math import isfinite
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from nxtrep_backend.agents.tools.body import (
    build_body_draft_tools,
    build_body_read_tools,
)
from nxtrep_backend.agents.tools.common import json_safe
from nxtrep_backend.agents.tools.confirmation import (
    build_confirmation_cancel_tools,
    build_confirmation_tools,
)
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.agents.tools.draft_revision import (
    build_pending_revision_tools,
    pending_revision_preflight,
)
from nxtrep_backend.agents.tools.exercise import build_exercise_tools
from nxtrep_backend.agents.tools.journal import (
    AgentToolJournal,
    argument_fingerprint,
    is_side_effect,
    side_effect_result_is_valid,
)
from nxtrep_backend.agents.tools.knowledge import build_knowledge_tools
from nxtrep_backend.agents.tools.meal_contract import meal_action_preflight
from nxtrep_backend.agents.tools.memory import (
    build_memory_read_tools,
    build_memory_write_tools,
)
from nxtrep_backend.agents.tools.nutrition import (
    build_food_catalog_draft_tools,
    build_nutrition_draft_tools,
    build_nutrition_read_tools,
)
from nxtrep_backend.agents.tools.nutrition_changes import build_saved_meal_change_tools
from nxtrep_backend.agents.tools.profile import build_profile_draft_tools, build_profile_tools
from nxtrep_backend.agents.tools.review import build_review_tools
from nxtrep_backend.agents.tools.training import (
    build_training_draft_tools,
    build_training_read_tools,
)
from nxtrep_backend.agents.tools.water import build_water_draft_tools, build_water_read_tools
from nxtrep_backend.agents.tools.web import build_web_tools
from nxtrep_backend.agents.tools.workout import (
    build_workout_correction_tools,
    build_workout_draft_tools,
    build_workout_read_tools,
)
from nxtrep_backend.agents.tools.workout_record import build_workout_record_tools
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.agent_errors import public_agent_error

ToolGroup = Literal[
    "profile",
    "profile_draft",
    "exercise",
    "knowledge",
    "web",
    "review",
    "training_read",
    "training_draft",
    "workout_read",
    "workout_draft",
    "workout_correction",
    "workout_record",
    "nutrition_read",
    "water_read",
    "water_draft",
    "nutrition_draft",
    "nutrition_changes",
    "food_catalog_draft",
    "body_read",
    "body_draft",
    "memory_read",
    "memory_write",
    "confirmation",
    "confirmation_cancel",
    "draft_revision",
]
ToolBuilder = Callable[[AgentToolContext], list[BaseTool]]

TOOL_GROUP_BUILDERS: dict[ToolGroup, ToolBuilder] = {
    "profile": build_profile_tools,
    "profile_draft": build_profile_draft_tools,
    "exercise": build_exercise_tools,
    "knowledge": build_knowledge_tools,
    "web": build_web_tools,
    "review": build_review_tools,
    "training_read": build_training_read_tools,
    "training_draft": build_training_draft_tools,
    "workout_read": build_workout_read_tools,
    "workout_draft": build_workout_draft_tools,
    "workout_correction": build_workout_correction_tools,
    "workout_record": build_workout_record_tools,
    "nutrition_read": build_nutrition_read_tools,
    "water_read": build_water_read_tools,
    "water_draft": build_water_draft_tools,
    "nutrition_draft": build_nutrition_draft_tools,
    "nutrition_changes": build_saved_meal_change_tools,
    "food_catalog_draft": build_food_catalog_draft_tools,
    "body_read": build_body_read_tools,
    "body_draft": build_body_draft_tools,
    "memory_read": build_memory_read_tools,
    "memory_write": build_memory_write_tools,
    "confirmation": build_confirmation_tools,
    "confirmation_cancel": build_confirmation_cancel_tools,
    "draft_revision": build_pending_revision_tools,
}

ALL_READ_GROUPS = frozenset(
    {
        "profile",
        "exercise",
        "training_read",
        "workout_read",
        "nutrition_read",
        "water_read",
        "body_read",
        "memory_read",
        "confirmation",
        "knowledge",
        "web",
        "review",
    }
)

TASK_TOOL_GROUPS: dict[str, frozenset[ToolGroup]] = {
    "water_record_draft": frozenset(
        {"water_read", "water_draft", "confirmation", "draft_revision"}
    ),
    "workout_record_draft": frozenset(
        {"exercise", "workout_read", "workout_record", "confirmation"}
    ),
    "workout_record_update_draft": frozenset({"workout_read", "workout_record", "confirmation"}),
    "workout_record_void_draft": frozenset({"workout_read", "workout_record", "confirmation"}),
    "nutrition_entry_update_draft": frozenset(
        {"nutrition_read", "nutrition_changes", "confirmation"}
    ),
    "nutrition_entry_delete_draft": frozenset(
        {"nutrition_read", "nutrition_changes", "confirmation"}
    ),
    "workout_set_update_draft": frozenset({"workout_read", "workout_correction", "confirmation"}),
    "workout_set_void_draft": frozenset({"workout_read", "workout_correction", "confirmation"}),
    "profile_update_draft": frozenset(
        {"profile", "profile_draft", "confirmation", "draft_revision"}
    ),
    "confirmation_cancel": frozenset({"confirmation", "confirmation_cancel"}),
    "schedule_change_draft": frozenset(
        {"profile", "training_read", "training_draft", "body_read", "confirmation"}
    ),
    "training_progression_draft": frozenset(
        {"profile", "training_read", "workout_read", "workout_draft", "confirmation"}
    ),
    "general_question": ALL_READ_GROUPS,
    "body_assessment": frozenset(),
    "body_progress_comparison": frozenset(
        {"profile", "body_read", "workout_read", "nutrition_read"}
    ),
    "body_measurement_draft": frozenset(
        {"profile", "body_read", "body_draft", "confirmation", "draft_revision"}
    ),
    "memory_write": frozenset({"memory_read", "memory_write"}),
    "food_catalog_draft": frozenset(
        {"nutrition_read", "food_catalog_draft", "confirmation", "web", "draft_revision"}
    ),
    "nutrition_analysis": frozenset(),
    "nutrition_target_draft": frozenset(
        {
            "profile",
            "body_read",
            "nutrition_read",
            "nutrition_draft",
            "confirmation",
            "draft_revision",
        }
    ),
    "nutrition_record_draft": frozenset(
        {"profile", "nutrition_read", "nutrition_draft", "confirmation", "web"}
    ),
    "training_plan_draft": frozenset(
        {
            "profile",
            "exercise",
            "training_read",
            "training_draft",
            "workout_read",
            "workout_draft",
            "body_read",
            "confirmation",
            "draft_revision",
        }
    ),
    "structured_data_query": ALL_READ_GROUPS,
    "knowledge_retrieval": frozenset({"knowledge", "web"}),
}

CONTEXT_TO_GROUP: dict[str, ToolGroup] = {
    "profile": "profile",
    "goal": "profile",
    "constraints": "profile",
    "exercise": "exercise",
    "training_plan": "training_read",
    "calendar": "training_read",
    "workout": "workout_read",
    "nutrition": "nutrition_read",
    "water": "water_read",
    "body": "body_read",
    "progress": "review",
    "memory": "memory_read",
    "confirmation": "confirmation",
    "knowledge": "knowledge",
}

# Only actual command targets are constrained. Searching another entity is safe;
# a new exercise appended to a bound session intentionally has a new exercise ID.
TARGET_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "read_pending_business_draft": {"confirmation_id": ("confirmation_id",)},
    "propose_pending_draft_revision": {"confirmation_id": ("confirmation_id",)},
    "propose_saved_meal_update": {"entry_id": ("entry_id", "meal_id")},
    "propose_saved_meal_delete": {"entry_id": ("entry_id", "meal_id")},
    "propose_saved_meal_item_remove": {"entry_id": ("entry_id", "meal_id")},
    "propose_nutrition_entry_revision": {"confirmation_id": ("confirmation_id",)},
    "cancel_confirmation": {"confirmation_id": ("confirmation_id",)},
    "propose_custom_food_update": {"food_id": ("food_id",)},
    "propose_custom_food_delete": {"food_id": ("food_id",)},
    "update_memory": {"memory_id": ("memory_id",)},
    "delete_memory": {"memory_id": ("memory_id",)},
    "propose_workout_set_update": {
        "workout_id": ("workout_id", "session_id"),
        "set_id": ("set_id",),
    },
    "propose_workout_set_void": {"workout_id": ("workout_id", "session_id"), "set_id": ("set_id",)},
    "propose_workout_record": {"workout_id": ("workout_id", "session_id")},
    "propose_workout_record_update": {
        "workout_id": ("workout_id", "session_id"),
        "workout_exercise_id": ("workout_exercise_id",),
    },
    "propose_workout_record_void": {
        "workout_id": ("workout_id", "session_id"),
        "workout_exercise_id": ("workout_exercise_id",),
    },
    "propose_progression": {"workout_id": ("workout_id", "session_id")},
    "propose_schedule_change": {
        "missed_event_id": ("event_id",),
        "replaces_confirmation_id": ("confirmation_id",),
    },
    "propose_recovery_adjustment": {"event_id": ("event_id",)},
}


def _scope_preflight(tool_name: str, arguments: dict, scope: dict) -> dict | None:
    if not isinstance(scope, dict) or not scope:
        return None
    operation_error = meal_action_preflight(tool_name, arguments, scope)
    if operation_error:
        return operation_error
    if tool_name in {"propose_nutrition_entry", "propose_nutrition_entry_from_reference"} and any(
        scope.get(name) for name in ("confirmation_id", "entry_id", "meal_id")
    ):
        saved = any(scope.get(name) for name in ("entry_id", "meal_id"))
        return {
            "status": "needs_review",
            "error_code": "MEAL_REVISION_REQUIRED",
            "required_tool": "propose_saved_meal_update"
            if saved
            else "propose_nutrition_entry_revision",
            "message": (
                "当前任务已经绑定原来的餐食，请修改该餐或对应待确认草稿，不能另建一餐。"
                "如果确实另吃了一餐，请明确切换到新的记餐任务。"
            ),
        }
    if tool_name == "propose_nutrition_entry_from_reference":
        reference = scope.get("_reference_entities") or {}
        expected_source = reference.get("entry_id") or reference.get("meal_id")
        if expected_source and str(arguments.get("source_entry_id")) != str(expected_source):
            return {"status": "needs_review", "error_code": "REFERENCE_ENTITY_CONFLICT",
                    "message": "参考餐食与本轮计划不一致，请重新核对参考对象。"}
    nested = arguments.get("request")
    nested = nested.model_dump() if isinstance(nested, BaseModel) else nested
    if scope.get("item_index") is not None and tool_name in {
        "propose_saved_meal_update", "propose_saved_meal_item_remove",
        "propose_saved_meal_delete", "propose_nutrition_entry_revision",
    }:
        body = nested if isinstance(nested, dict) else arguments
        changes = [c.model_dump() if isinstance(c, BaseModel) else c
                   for c in body.get("changes", [])]
        indices = {c.get("item_index") for c in changes}
        indices.update(body.get("remove_item_indices") or [])
        if body.get("item_index") is not None:
            indices.add(body["item_index"])
        if tool_name == "propose_saved_meal_delete" or indices - {scope["item_index"]}:
            return {"status": "needs_review", "error_code": "TASK_ITEM_CONFLICT",
                    "message": "要修改的食物与当前选中的项目不一致，请核对食物后再生成草稿。"}
    for argument, aliases in TARGET_FIELDS.get(tool_name, {}).items():
        expected = {str(scope[name]) for name in aliases if scope.get(name) is not None}
        if not expected:
            continue
        supplied = arguments.get(argument)
        if supplied is None and isinstance(nested, dict):
            supplied = nested.get(argument)
        try:
            supplied = str(UUID(str(supplied)))
            expected = {str(UUID(value)) for value in expected}
        except (ValueError, TypeError, AttributeError):
            supplied = None
        if len(expected) != 1 or supplied not in expected:
            return {
                "status": "needs_review",
                "error_code": "TASK_ENTITY_CONFLICT",
                "missing_fields": [argument],
                "message": (
                    "这次操作的目标与当前任务不一致，尚未执行。"
                    "请明确要修改哪条记录，或切换到新任务。"
                ),
            }
    return None


_PRIVATE_TRACE_KEYS = re.compile(
    r"(?:password|passwd|secret|token|authorization|credential|api[_-]?key|cookie|"
    r"image[_-]?(?:data|bytes)|base64|binary|notes|content|user_message|message|instructions|密码|密钥|令牌)",
    re.IGNORECASE,
)
_CREDENTIAL_TEXT = re.compile(
    r"(?:\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:password|secret|token|api[_-]?key|密码|密钥|令牌)\s*(?:[:=：]|是)\s*\S+)",
    re.IGNORECASE,
)


def safe_trace_snapshot(value, *, depth: int = 0):
    """Keep bounded business parameters/results, excluding credentials and free prose."""
    if depth > 4:
        return "[truncated]"
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_unset=True)
    else:
        value = json_safe(value)
    if isinstance(value, float) and not isfinite(value):
        return "[invalid number]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _CREDENTIAL_TEXT.sub("[redacted]", value)[:240]
    if isinstance(value, dict):
        result = {
            str(key)[:64]: "[redacted]"
            if _PRIVATE_TRACE_KEYS.search(str(key))
            else safe_trace_snapshot(item, depth=depth + 1)
            for key, item in list(value.items())[:20]
        }
        if len(json.dumps(result, ensure_ascii=False)) > 4096:
            return {"truncated": True, "keys": list(result)}
        return result
    if isinstance(value, (list, tuple)):
        return [safe_trace_snapshot(item, depth=depth + 1) for item in value[:8]]
    return "[unsupported]"


def groups_for_task(task: AgentIntentTask) -> frozenset[ToolGroup]:
    if task.task_type == "structured_data_query" and task.required_context:
        groups: set[ToolGroup] = set()
    else:
        groups = set(TASK_TOOL_GROUPS.get(task.task_type, frozenset()))
    for context_name in task.required_context:
        group = CONTEXT_TO_GROUP.get(context_name)
        if group is not None:
            groups.add(group)
    return frozenset(groups)


def build_tools(
    context: AgentToolContext,
    *,
    groups: Iterable[ToolGroup] | None = None,
) -> list[BaseTool]:
    requested_groups = set(groups) if groups is not None else set(TOOL_GROUP_BUILDERS)
    unknown_groups = requested_groups - set(TOOL_GROUP_BUILDERS)
    if unknown_groups:
        names = ", ".join(sorted(unknown_groups))
        raise ValueError(f"Unknown Agent tool group: {names}")

    selected_groups = [
        group_name for group_name in TOOL_GROUP_BUILDERS if group_name in requested_groups
    ]
    tools: list[BaseTool] = []
    used_names: set[str] = set()

    for group_name in selected_groups:
        builder = TOOL_GROUP_BUILDERS[group_name]

        for current_tool in builder(context):
            if current_tool.name in used_names:
                raise ValueError(f"Duplicate Agent tool name: {current_tool.name}")
            _serialize_async_tool(
                current_tool,
                context.operation_lock,
                context.tool_runs,
                journal=context.journal if isinstance(context.journal, AgentToolJournal) else None,
                task_scope=context.task_scope if isinstance(context.task_scope, dict) else {},
                task_id=context.task_id if isinstance(context.task_id, UUID) else None,
                trace_context=context.trace_context
                if isinstance(context.trace_context, dict)
                else {},
                tool_context=context,
            )
            tools.append(current_tool)
            used_names.add(current_tool.name)

    return tools


def _serialize_async_tool(
    tool: BaseTool,
    lock: asyncio.Lock,
    runs: list[dict],
    *,
    journal: AgentToolJournal | None = None,
    task_scope: dict | None = None,
    task_id: UUID | None = None,
    trace_context: dict | None = None,
    tool_context: AgentToolContext | None = None,
) -> None:
    """Serialize the existing tool and guard duplicate writes in the same Agent run."""
    original = getattr(tool, "coroutine", None)
    if original is None:
        return
    journal = journal or AgentToolJournal()
    parameters = signature(original)
    side_effect = is_side_effect(tool.name)
    trace_context = trace_context or {}

    @wraps(original)
    async def serialized(*args, **kwargs):
        async with lock:
            started = monotonic()
            record = {"tool_name": tool.name, "status": "failed", "tool_call_id": str(uuid4())}
            if trace_context:
                for field in ("conversation_id", "turn_id", "trace_id"):
                    value = trace_context.get(field)
                    if isinstance(value, (str, UUID)):
                        record[field] = str(value)[:80]
                if task_id is not None:
                    record["task_id"] = str(task_id)
                # The coroutine boundary cannot see a provider ToolCall ID.
                # This generated UUID identifies the gateway execution instead.
                record["tool_call_id_source"] = "gateway"
            key = None
            invoked = False
            try:
                bound = parameters.bind(*args, **kwargs)
                bound.apply_defaults()
                if trace_context:
                    record["arguments_snapshot"] = safe_trace_snapshot(bound.arguments)
                record["argument_fingerprint"] = argument_fingerprint(bound.arguments)
                key = f"{tool.name}:{record['argument_fingerprint']}"
                preflight = _scope_preflight(tool.name, bound.arguments, task_scope or {})
                if preflight is None:
                    preflight = await pending_revision_preflight(
                        tool.name, tool_context, task_scope or {}
                    )
                if preflight is not None:
                    record["status"] = preflight["status"]
                    record["error_code"] = preflight["error_code"]
                    if trace_context:
                        record["result_snapshot"] = safe_trace_snapshot(preflight)
                    return preflight
                result = journal.replay(key) if side_effect else None
                if result is not None:
                    record["replayed"] = True
                else:
                    result = journal.guard(key)
                    if result is None:
                        invoked = True
                        result = await original(*args, **kwargs)
                        if side_effect:
                            journal.note_returned_refs(result)
                            if not side_effect_result_is_valid(tool.name, result):
                                record["error_code"] = "TOOL_RESULT_INVALID"
                                journal.outcome_unknown(key, record)
                                result = {
                                    "status": "needs_review",
                                    "error_code": "TOOL_RESULT_INVALID",
                                    "message": (
                                        "工具返回不完整，尚不能核实操作结果。"
                                        "请先核对记录或待确认草稿，不能重复写入。"
                                    ),
                                }
                        else:
                            journal.observe_read(key, result)
                record["status"] = (
                    result.get("status", "completed") if isinstance(result, dict) else "completed"
                )
                if isinstance(result, dict) and isinstance(result.get("error_code"), str):
                    record["error_code"] = result["error_code"]
                if trace_context:
                    record["result_snapshot"] = safe_trace_snapshot(result)
                if invoked and side_effect:
                    journal.succeeded(key, result, record)
                return result
            except asyncio.CancelledError:
                record["error_code"] = "TOOL_INTERRUPTED_UNKNOWN"
                if invoked and side_effect and key is not None:
                    journal.outcome_unknown(key, record)
                raise
            except Exception as exc:
                record["error_code"] = public_agent_error(exc).code
                known_failure = isinstance(exc, ValueError) or record["error_code"] in {
                    "BUSINESS_RULE_VIOLATION",
                    "BUSINESS_STATE_CONFLICT",
                    "RECORD_NOT_FOUND",
                    "MODEL_ACCESS_DENIED",
                    "AGENT_RESULT_INVALID",
                    "MODEL_BUSY",
                }
                if invoked and side_effect and key is not None and not known_failure:
                    journal.outcome_unknown(key, record)
                raise
            finally:
                record["duration_ms"] = max(0, round((monotonic() - started) * 1000))
                if isinstance(runs, list):
                    runs.append(record)
                journal.record_call(record)

    tool.coroutine = serialized
