from unittest.mock import MagicMock

import pytest

import nxtrep_backend.agents.runtime as runtime_module
from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.core.config import Settings


def test_build_agent_registers_selected_context_tools(monkeypatch) -> None:
    settings = MagicMock(spec=Settings)
    context = MagicMock(spec=AgentToolContext)
    groups = frozenset({"profile", "exercise"})
    model = MagicMock()
    selected_tools = [MagicMock()]
    agent = MagicMock()
    create_agent = MagicMock(return_value=agent)
    build_tools = MagicMock(return_value=selected_tools)

    monkeypatch.setattr(
        runtime_module,
        "build_chat_model",
        MagicMock(return_value=model),
    )
    monkeypatch.setattr(runtime_module, "build_tools", build_tools)
    monkeypatch.setattr(runtime_module, "create_agent", create_agent)

    result = runtime_module.build_agent(
        settings,
        tool_context=context,
        tool_groups=groups,
    )

    assert result is agent
    build_tools.assert_called_once_with(context, groups=groups)
    create_agent.assert_called_once_with(
        model=model,
        tools=selected_tools,
        system_prompt=runtime_module.SYSTEM_PROMPT,
        name="nxtrep_coach",
    )


def test_build_agent_supports_tool_free_legacy_mode(monkeypatch) -> None:
    create_agent = MagicMock(return_value=MagicMock())
    build_tools = MagicMock()
    monkeypatch.setattr(
        runtime_module,
        "build_chat_model",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(runtime_module, "build_tools", build_tools)
    monkeypatch.setattr(runtime_module, "create_agent", create_agent)

    runtime_module.build_agent(MagicMock(spec=Settings))

    build_tools.assert_not_called()
    assert create_agent.call_args.kwargs["tools"] == []


def test_training_plan_agent_receives_task_specific_tool_instruction(monkeypatch) -> None:
    create_agent = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(runtime_module, "create_agent", create_agent)
    monkeypatch.setattr(runtime_module, "build_tools", MagicMock(return_value=[]))

    runtime_module.build_agent(
        MagicMock(spec=Settings),
        tool_context=MagicMock(spec=AgentToolContext),
        tool_groups=frozenset({"training_draft"}),
        model=MagicMock(),
        task_type="training_plan_draft",
    )

    prompt = create_agent.call_args.kwargs["system_prompt"]
    assert "propose_training_plan" in prompt
    assert "仅输出文字计划不算完成" in prompt


def test_build_agent_rejects_groups_without_context() -> None:
    with pytest.raises(ValueError, match="tool_context is required"):
        runtime_module.build_agent(
            MagicMock(spec=Settings),
            tool_groups=frozenset({"profile"}),
        )
