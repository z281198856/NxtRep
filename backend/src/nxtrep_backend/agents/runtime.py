from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel

from nxtrep_backend.agents.prompts import SYSTEM_PROMPT
from nxtrep_backend.agents.tools import AgentToolContext, ToolGroup, build_tools
from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.models import build_text_model


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Backward-compatible Agent entrypoint delegated to the model gateway."""
    return build_text_model(settings)


def build_agent(
    settings: Settings,
    *,
    tool_context: AgentToolContext | None = None,
    tool_groups: frozenset[ToolGroup] | None = None,
    model: BaseChatModel | None = None,
):
    if tool_context is None and tool_groups is not None:
        raise ValueError("tool_context is required when tool_groups are provided")

    tools = build_tools(tool_context, groups=tool_groups) if tool_context is not None else []

    return create_agent(
        model=model or build_chat_model(settings),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        name="nxtrep_coach",
    )
