import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from nxtrep_backend.agents.synthesis import (
    AgentResponseSynthesisError,
    AgentResponseSynthesizer,
)
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentExecutionBundle,
)


def make_execution_bundle() -> AgentExecutionBundle:
    body_asset_id = uuid4()
    food_asset_id = uuid4()

    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_assessment",
                asset_ids=[body_asset_id],
                status="completed",
                result={
                    "summary": "Shoulder height may be asymmetric",
                },
            ),
            AgentBranchResult(
                task_type="nutrition_analysis",
                asset_ids=[food_asset_id],
                status="completed",
                result={
                    "foods": ["rice", "chicken"],
                    "estimated_kcal": 520,
                },
                requires_confirmation=True,
            ),
        ],
        clarification_questions=[
            "How much cooking oil was used?",
        ],
    )


def make_model(response: AIMessage) -> MagicMock:
    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock(return_value=response)
    return model


def make_stream_model(*chunks: str, error: Exception | None = None) -> MagicMock:
    model = MagicMock(spec=BaseChatModel)

    async def stream(_messages):
        for chunk in chunks:
            yield AIMessageChunk(content=chunk)
        if error is not None:
            raise error

    model.astream = MagicMock(side_effect=stream)
    return model


@pytest.mark.asyncio
async def test_synthesizer_sends_all_branch_results_to_text_model() -> None:
    model = make_model(
        AIMessage(
            content=("这顿饭估算约 520 千卡；图片估算存在误差，请确认食物份量和用油量后再保存。")
        )
    )
    bundle = make_execution_bundle()
    synthesizer = AgentResponseSynthesizer(model)

    result = await synthesizer.synthesize(
        user_message="分析我的体态和这顿饭",
        execution_bundle=bundle,
    )

    assert result.endswith("再保存。")
    model.ainvoke.assert_awaited_once()
    messages = model.ainvoke.await_args.args[0]

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "Memory 已经生效" in messages[0].content
    assert "其他正式业务数据不得声称已保存" in messages[0].content

    payload = json.loads(messages[1].content)
    assert payload["user_message"] == "分析我的体态和这顿饭"
    assert len(payload["execution_bundle"]["branch_results"]) == 2
    nutrition_result = payload["execution_bundle"]["branch_results"][1]
    assert nutrition_result["requires_confirmation"] is True
    assert payload["execution_bundle"]["clarification_questions"] == [
        "How much cooking oil was used?"
    ]


@pytest.mark.asyncio
async def test_synthesizer_strips_model_response() -> None:
    model = make_model(AIMessage(content="  请补充一张清晰的食物图片。  "))
    synthesizer = AgentResponseSynthesizer(model)

    result = await synthesizer.synthesize(
        user_message="分析饮食",
        execution_bundle=make_execution_bundle(),
    )

    assert result == "请补充一张清晰的食物图片。"


@pytest.mark.asyncio
async def test_synthesizer_rejects_empty_model_response() -> None:
    model = make_model(AIMessage(content="   "))
    synthesizer = AgentResponseSynthesizer(model)

    with pytest.raises(
        AgentResponseSynthesisError,
        match="empty response",
    ):
        await synthesizer.synthesize(
            user_message="分析饮食",
            execution_bundle=make_execution_bundle(),
        )


@pytest.mark.asyncio
async def test_synthesizer_uses_fallback_when_primary_fails() -> None:
    primary = make_model(AIMessage(content="unused"))
    primary.ainvoke.side_effect = TimeoutError("primary timeout")
    fallback = make_model(AIMessage(content="备用模型回答"))

    result = await AgentResponseSynthesizer(primary, fallback).synthesize(
        user_message="分析饮食",
        execution_bundle=make_execution_bundle(),
    )

    assert result == "备用模型回答"
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_synthesizer_streams_native_model_deltas_without_buffering_answer() -> None:
    release_remainder = asyncio.Event()
    model = MagicMock(spec=BaseChatModel)

    async def stream(_messages):
        yield AIMessageChunk(content="  你")
        await release_remainder.wait()
        yield AIMessageChunk(content="好")
        yield AIMessageChunk(content=" ")
        yield AIMessageChunk(content="呀  ")

    model.astream = MagicMock(side_effect=stream)
    synthesizer = AgentResponseSynthesizer(model)

    stream = synthesizer.astream(
        user_message="给我建议",
        execution_bundle=make_execution_bundle(),
    )

    assert await asyncio.wait_for(anext(stream), timeout=0.1) == "你"
    assert not release_remainder.is_set()
    release_remainder.set()
    assert [item async for item in stream] == ["好", " 呀"]
    model.astream.assert_called_once()
    assert len(model.astream.call_args.args[0]) == 2


@pytest.mark.asyncio
async def test_synthesizer_stream_falls_back_only_before_output_starts() -> None:
    primary = make_stream_model(error=TimeoutError("primary timeout"))
    fallback = make_stream_model("备用", "回答")
    synthesizer = AgentResponseSynthesizer(primary, fallback)

    chunks = [
        item
        async for item in synthesizer.astream(
            user_message="给我建议",
            execution_bundle=make_execution_bundle(),
        )
    ]

    assert chunks == ["备用", "回答"]
    primary.astream.assert_called_once()
    fallback.astream.assert_called_once()


@pytest.mark.asyncio
async def test_synthesizer_stream_never_splices_fallback_after_partial_output() -> None:
    primary = make_stream_model("部分", error=TimeoutError("stream interrupted"))
    fallback = make_stream_model("不应出现")
    synthesizer = AgentResponseSynthesizer(primary, fallback)
    stream = synthesizer.astream(
        user_message="给我建议",
        execution_bundle=make_execution_bundle(),
    )

    assert await anext(stream) == "部分"
    with pytest.raises(AgentResponseSynthesisError, match="after output started"):
        await anext(stream)
    fallback.astream.assert_not_called()
