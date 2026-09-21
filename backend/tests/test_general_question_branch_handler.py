import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.schemas.agent import AgentCitation, AgentIntentTask
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_context import ActiveMemoryContext
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import (
    GeneralQuestionBranchHandler,
    GeneralQuestionResponseError,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


def make_react_agent(result: dict) -> MagicMock:
    agent = MagicMock(spec=CompiledStateGraph)
    agent.ainvoke = AsyncMock(return_value=result)
    return agent


def make_handler(react_agent: MagicMock):
    return GeneralQuestionBranchHandler(lambda task: react_agent)


def make_input(
    *,
    task_type: str = "general_question",
    missing_fields=None,
    required_context=None,
) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message="深蹲时应该怎样呼吸？",
        task=AgentIntentTask(
            task_type=task_type,
            asset_ids=[],
            required_context=(["profile"] if required_context is None else required_context),
            missing_fields=missing_fields or [],
            confidence="high",
            routing_reason="The user asked a general fitness question",
        ),
        images=(),
    )


@pytest.mark.asyncio
async def test_plain_general_question_defers_to_native_streaming_synthesis() -> None:
    react_agent = make_react_agent({})
    handler = make_handler(react_agent)
    memory = ActiveMemoryContext(
        id=uuid4(),
        category="communication_preference",
        content="请使用中文回答",
        version=1,
    )
    branch_input = make_input(required_context=[])
    branch_input = AgentBranchInput(
        user_id=branch_input.user_id,
        message="你好",
        task=branch_input.task,
        images=(),
        memories=(memory,),
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert result.result == {
        "response_mode": "direct_general_question",
        "active_long_term_memories": [memory.as_dict()],
    }
    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_returns_trimmed_react_answer() -> None:
    react_agent = make_react_agent(
        {"messages": [AIMessage(content=("  下蹲时吸气并保持躯干稳定，起身通过发力点后呼气。  "))]}
    )
    handler = make_handler(react_agent)
    branch_input = make_input()

    result = await handler.execute(branch_input)

    react_agent.ainvoke.assert_awaited_once_with(
        {
            "messages": [
                {
                    "role": "user",
                    "content": branch_input.message,
                }
            ]
        }
    )
    assert result.status == "completed"
    assert result.result == {"answer": "下蹲时吸气并保持躯干稳定，起身通过发力点后呼气。"}
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_handler_includes_vision_observation_for_image_question() -> None:
    react_agent = make_react_agent({"messages": [AIMessage(content="这张图展示了一个深蹲动作。")]})
    analyzer = MagicMock(spec=GlmVisionAnalyzer)
    analyzer.analyze = AsyncMock(return_value="观察到用户处于深蹲底部位置。")
    handler = GeneralQuestionBranchHandler(
        lambda task: react_agent,
        vision_analyzer=analyzer,
    )
    asset_id = uuid4()
    image = ResolvedAgentImage(
        asset_id=asset_id,
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-image",
    )
    base_input = make_input(required_context=[])
    branch_input = AgentBranchInput(
        user_id=base_input.user_id,
        message="帮我看看这个动作",
        task=AgentIntentTask(
            task_type="general_question",
            asset_ids=[asset_id],
            required_context=[],
            missing_fields=[],
            confidence="high",
            routing_reason="The user asked about an attached image",
        ),
        images=(image,),
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    analyzer.analyze.assert_awaited_once_with(
        question="帮我看看这个动作",
        images=(image,),
    )
    react_agent.ainvoke.assert_awaited_once()
    content = react_agent.ainvoke.await_args.args[0]["messages"][-1]["content"]
    assert "帮我看看这个动作" in content
    assert "观察到用户处于深蹲底部位置。" in content
    assert "c2FuaXRpemVkLWltYWdl" not in content


@pytest.mark.asyncio
async def test_handler_returns_missing_fields_without_calling_react() -> None:
    react_agent = make_react_agent({})
    handler = make_handler(react_agent)
    branch_input = make_input(
        missing_fields=["training_goal", "training_goal"],
    )

    result = await handler.execute(branch_input)

    assert result.status == "needs_input"
    assert result.missing_fields == ["training_goal"]
    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_rejects_knowledge_task_when_rag_is_disabled() -> None:
    react_agent = make_react_agent({})
    handler = GeneralQuestionBranchHandler(
        lambda task: react_agent,
        knowledge_retrieval_enabled=False,
    )

    result = await handler.execute(make_input(task_type="knowledge_retrieval"))

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "RAG_UNAVAILABLE"
    assert result.error.retryable is False
    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_propagates_confirmation_requirement() -> None:
    confirmation_id = uuid4()
    react_agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "draft": {"id": str(uuid4()), "version": 1},
                            "confirmation": {
                                "confirmation_id": str(confirmation_id),
                                "operation_type": "training_plan_activate",
                                "status": "pending",
                                "before": None,
                                "after": {"plan_draft_id": str(uuid4())},
                                "impact": "activate training plan",
                                "expires_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
                                "version": 1,
                            },
                        }
                    ),
                    tool_call_id="call-1",
                ),
                AIMessage(content="提案已创建，请在确认卡片中批准。"),
            ]
        }
    )
    handler = make_handler(react_agent)

    result = await handler.execute(make_input(task_type="training_plan_draft"))

    assert result.requires_confirmation is True
    assert len(result.operation_results) == 1
    assert result.confirmation_cards[0].confirmation_id == confirmation_id


@pytest.mark.asyncio
async def test_handler_propagates_knowledge_citations() -> None:
    react_agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "available",
                            "evidence": [
                                {
                                    "content": "下蹲阶段吸气并保持躯干稳定。",
                                    "citation": {
                                        "source_key": "squat-guide",
                                        "source_title": "深蹲动作指南",
                                        "source_uri": "https://example.com/squat",
                                        "source_version": 3,
                                        "section_path": "动作要领 > 呼吸",
                                        "page_numbers": [4],
                                    },
                                },
                                {
                                    "content": "起身通过发力点后呼气。",
                                    "citation": {
                                        "source_key": "squat-guide",
                                        "source_title": "深蹲动作指南",
                                        "source_uri": "https://example.com/squat",
                                        "source_version": 3,
                                        "section_path": "动作要领 > 呼吸",
                                        "page_numbers": [5],
                                    },
                                },
                            ],
                        }
                    ),
                    tool_call_id="call-knowledge",
                ),
                AIMessage(content="下蹲时吸气，起身通过发力点后呼气。"),
            ]
        }
    )
    handler = make_handler(react_agent)

    result = await handler.execute(make_input(task_type="knowledge_retrieval"))

    assert result.citations == [
        AgentCitation(
            source_type="knowledge",
            source_id="squat-guide@3",
            label="深蹲动作指南 / 动作要领 > 呼吸 / 第4-5页",
        )
    ]


@pytest.mark.asyncio
async def test_handler_injects_recent_history_summary_and_relevant_memories() -> None:
    react_agent = make_react_agent({"messages": [AIMessage(content="安排好了")]})
    handler = make_handler(react_agent)
    branch_input = make_input(task_type="training_plan_draft")
    branch_input = AgentBranchInput(
        user_id=branch_input.user_id,
        message="那帮我安排一下",
        task=branch_input.task,
        images=(),
        conversation_context=AgentConversationContext(
            summary="用户计划增肌",
            recent_messages=(
                ConversationMessageContext(role="user", content="我每周练三天"),
                ConversationMessageContext(role="assistant", content="了解"),
            ),
        ),
        memories=(
            ActiveMemoryContext(
                id=uuid4(),
                category="equipment",
                content="只有哑铃",
                version=1,
            ),
        ),
    )

    await handler.execute(branch_input)

    messages = react_agent.ainvoke.await_args.args[0]["messages"]
    assert "用户计划增肌" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "我每周练三天"}
    assert messages[2] == {"role": "assistant", "content": "了解"}
    assert "只有哑铃" in messages[-1]["content"]
    assert "那帮我安排一下" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_handler_rejects_wrong_task_type() -> None:
    react_agent = make_react_agent({})
    handler = make_handler(react_agent)

    with pytest.raises(ValueError, match="text task"):
        await handler.execute(make_input(task_type="nutrition_analysis"))

    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "react_result, error_message",
    [
        ({}, "no messages"),
        ({"messages": []}, "no messages"),
        ({"messages": [AIMessage(content="   ")]}, "no answer"),
        (
            {
                "messages": [
                    AIMessage(
                        content=[
                            {
                                "type": "text",
                                "text": "unexpected block",
                            }
                        ]
                    )
                ]
            },
            "no answer",
        ),
    ],
)
async def test_handler_rejects_invalid_react_result(
    react_result: dict,
    error_message: str,
) -> None:
    handler = make_handler(make_react_agent(react_result))

    with pytest.raises(
        GeneralQuestionResponseError,
        match=error_message,
    ):
        await handler.execute(make_input())
