from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from nxtrep_backend.agents.vision import (
    GlmVisionAnalyzer,
    VisionModelResponseError,
    build_glm_vision_content,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-image",
    )


def make_model() -> MagicMock:
    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock()
    return model


@pytest.mark.asyncio
async def test_analyzer_sends_multimodal_human_message_to_vision_model() -> None:
    model = make_model()
    image = make_image()
    model.ainvoke.return_value = AIMessage(content="观察到肩部存在轻微高低差。")
    analyzer = GlmVisionAnalyzer(model)

    result = await analyzer.analyze(
        question="帮我分析体态",
        images=[image],
    )

    assert result == "观察到肩部存在轻微高低差。"
    model.ainvoke.assert_awaited_once()
    messages = model.ainvoke.await_args.args[0]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == build_glm_vision_content(
        question="帮我分析体态",
        images=[image],
    )


@pytest.mark.asyncio
async def test_analyzer_extracts_text_from_block_response() -> None:
    model = make_model()
    model.ainvoke.return_value = AIMessage(
        content=[
            {"type": "text", "text": "第一部分。"},
            {"type": "text", "text": "第二部分。"},
        ]
    )
    analyzer = GlmVisionAnalyzer(model)

    result = await analyzer.analyze(
        question="描述图片",
        images=[make_image()],
    )

    assert result == "第一部分。\n第二部分。"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "   ", []])
async def test_analyzer_rejects_empty_model_response(content: object) -> None:
    model = make_model()
    model.ainvoke.return_value = AIMessage(content=content)
    analyzer = GlmVisionAnalyzer(model)

    with pytest.raises(VisionModelResponseError):
        await analyzer.analyze(
            question="描述图片",
            images=[make_image()],
        )
