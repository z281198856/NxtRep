from dataclasses import is_dataclass, replace

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel

from nxtrep_backend.agents.prompts import SYSTEM_PROMPT, TASK_PROMPTS
from nxtrep_backend.agents.tools import AgentToolContext, ToolGroup, build_tools
from nxtrep_backend.agents.tools.draft_revision import REVISION_OPERATIONS
from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.models import build_text_model
from nxtrep_backend.schemas.agent import AgentTaskType


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Backward-compatible Agent entrypoint delegated to the model gateway."""
    return build_text_model(settings)


def build_agent(
    settings: Settings,
    *,
    tool_context: AgentToolContext | None = None,
    tool_groups: frozenset[ToolGroup] | None = None,
    model: BaseChatModel | None = None,
    task_type: AgentTaskType | None = None,
    food_catalog_actions: list[str] | None = None,
):
    if tool_context is None and tool_groups is not None:
        raise ValueError("tool_context is required when tool_groups are provided")

    if is_dataclass(tool_context):
        tool_context = replace(tool_context, task_type=task_type)
    tools = build_tools(tool_context, groups=tool_groups) if tool_context is not None else []
    proposal_for_task = {
        "workout_record_draft": "propose_workout_record",
        "workout_record_update_draft": "propose_workout_record_update",
        "workout_record_void_draft": "propose_workout_record_void",
        "nutrition_entry_update_draft": "propose_saved_meal_update",
        "nutrition_entry_delete_draft": "propose_saved_meal_delete",
        "workout_set_update_draft": "propose_workout_set_update",
        "workout_set_void_draft": "propose_workout_set_void",
        "profile_update_draft": "propose_profile_update",
        "food_catalog_draft": "propose_custom_food",
        "training_plan_draft": "propose_training_plan",
        "schedule_change_draft": "propose_schedule_change",
        "training_progression_draft": "propose_progression",
        "nutrition_record_draft": "propose_nutrition_entry",
        "nutrition_target_draft": "propose_nutrition_target",
        "body_measurement_draft": "propose_body_measurement",
        "water_record_draft": "propose_water_entry",
    }
    if task_type in proposal_for_task:
        permitted = {proposal_for_task[task_type]}
        if task_type == "food_catalog_draft":
            permitted = {
                {
                    "create": "propose_custom_food",
                    "update": "propose_custom_food_update",
                    "delete": "propose_custom_food_delete",
                }[action]
                for action in (food_catalog_actions or ["create"])
            }
        elif task_type == "nutrition_record_draft":
            permitted.add("propose_nutrition_entry_revision")
            permitted.add("propose_nutrition_entry_from_reference")
        elif task_type == "nutrition_entry_update_draft":
            permitted.add("propose_saved_meals_date_change")
        elif task_type == "nutrition_entry_delete_draft":
            permitted.add("propose_saved_meal_item_remove")
        elif task_type == "schedule_change_draft":
            permitted.add("propose_recovery_adjustment")
        if task_type in REVISION_OPERATIONS:
            permitted.add("propose_pending_draft_revision")
        tools = [
            item for item in tools if not item.name.startswith("propose_") or item.name in permitted
        ]

    return create_agent(
        model=model or build_chat_model(settings),
        tools=tools,
        system_prompt=(
            f"{SYSTEM_PROMPT}\n\n{TASK_PROMPTS[task_type]}"
            if task_type in TASK_PROMPTS
            else SYSTEM_PROMPT
        ),
        name="nxtrep_coach",
    )
