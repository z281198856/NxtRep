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
from nxtrep_backend.providers.model_errors import VisionModelBusyError
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


class CapacityError(RuntimeError):
    status_code = 429


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


@pytest.mark.asyncio
async def test_analyzer_uses_fallback_for_single_image_capacity_error() -> None:
    model = make_model()
    fallback_model = make_model()
    image = make_image()
    model.ainvoke.side_effect = CapacityError("busy")
    fallback_model.ainvoke.return_value = AIMessage(content="备用模型观察结果")
    analyzer = GlmVisionAnalyzer(model, fallback_model)

    result = await analyzer.analyze(question="描述图片", images=[image])

    assert result == "备用模型观察结果"
    model.ainvoke.assert_awaited_once()
    fallback_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyzer_does_not_drop_images_to_use_single_image_fallback() -> None:
    model = make_model()
    fallback_model = make_model()
    model.ainvoke.side_effect = CapacityError("busy")
    analyzer = GlmVisionAnalyzer(model, fallback_model)

    with pytest.raises(VisionModelBusyError):
        await analyzer.analyze(
            question="比较图片",
            images=[make_image(), make_image()],
        )

    fallback_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyzer_reports_busy_when_primary_and_fallback_are_at_capacity() -> None:
    model = make_model()
    fallback_model = make_model()
    model.ainvoke.side_effect = CapacityError("primary busy")
    fallback_model.ainvoke.side_effect = CapacityError("fallback busy")
    analyzer = GlmVisionAnalyzer(model, fallback_model)

    with pytest.raises(VisionModelBusyError):
        await analyzer.analyze(question="描述图片", images=[make_image()])
