import asyncio
from collections.abc import Callable, Iterable
from functools import wraps
from typing import Literal

from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.body import (
    build_body_draft_tools,
    build_body_read_tools,
)
from nxtrep_backend.agents.tools.confirmation import build_confirmation_tools
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.agents.tools.exercise import build_exercise_tools
from nxtrep_backend.agents.tools.knowledge import build_knowledge_tools
from nxtrep_backend.agents.tools.memory import (
    build_memory_read_tools,
    build_memory_write_tools,
)
from nxtrep_backend.agents.tools.nutrition import (
    build_nutrition_draft_tools,
    build_nutrition_read_tools,
)
from nxtrep_backend.agents.tools.profile import build_profile_tools
from nxtrep_backend.agents.tools.training import (
    build_training_draft_tools,
    build_training_read_tools,
)
from nxtrep_backend.agents.tools.workout import (
    build_workout_draft_tools,
    build_workout_read_tools,
)
from nxtrep_backend.schemas.agent import AgentIntentTask

ToolGroup = Literal[
    "profile",
    "exercise",
    "knowledge",
    "training_read",
    "training_draft",
    "workout_read",
    "workout_draft",
    "nutrition_read",
    "nutrition_draft",
    "body_read",
    "body_draft",
    "memory_read",
    "memory_write",
    "confirmation",
]
ToolBuilder = Callable[[AgentToolContext], list[BaseTool]]

TOOL_GROUP_BUILDERS: dict[ToolGroup, ToolBuilder] = {
    "profile": build_profile_tools,
    "exercise": build_exercise_tools,
    "knowledge": build_knowledge_tools,
    "training_read": build_training_read_tools,
    "training_draft": build_training_draft_tools,
    "workout_read": build_workout_read_tools,
    "workout_draft": build_workout_draft_tools,
    "nutrition_read": build_nutrition_read_tools,
    "nutrition_draft": build_nutrition_draft_tools,
    "body_read": build_body_read_tools,
    "body_draft": build_body_draft_tools,
    "memory_read": build_memory_read_tools,
    "memory_write": build_memory_write_tools,
    "confirmation": build_confirmation_tools,
}

ALL_READ_GROUPS = frozenset(
    {
        "profile",
        "exercise",
        "training_read",
        "workout_read",
        "nutrition_read",
        "body_read",
        "memory_read",
        "confirmation",
        "knowledge",
    }
)

TASK_TOOL_GROUPS: dict[str, frozenset[ToolGroup]] = {
    "general_question": ALL_READ_GROUPS,
    "body_assessment": frozenset(),
    "body_progress_comparison": frozenset(
        {"profile", "body_read", "workout_read", "nutrition_read"}
    ),
    "body_measurement_draft": frozenset({"profile", "body_read", "body_draft", "confirmation"}),
    "memory_write": frozenset({"memory_read", "memory_write"}),
    "nutrition_analysis": frozenset(),
    "nutrition_record_draft": frozenset(
        {"profile", "nutrition_read", "nutrition_draft", "confirmation"}
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
        }
    ),
    "structured_data_query": ALL_READ_GROUPS,
    "knowledge_retrieval": frozenset({"knowledge"}),
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
    "body": "body_read",
    "progress": "body_read",
    "memory": "memory_read",
    "confirmation": "confirmation",
    "knowledge": "knowledge",
}


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
            _serialize_async_tool(current_tool, context.operation_lock)
            tools.append(current_tool)
            used_names.add(current_tool.name)

    return tools


def _serialize_async_tool(tool: BaseTool, lock: asyncio.Lock) -> None:
    """Prevent concurrent tools from using the same request-scoped AsyncSession."""
    original = getattr(tool, "coroutine", None)
    if original is None:
        return

    @wraps(original)
    async def serialized(*args, **kwargs):
        async with lock:
            return await original(*args, **kwargs)

    tool.coroutine = serialized
