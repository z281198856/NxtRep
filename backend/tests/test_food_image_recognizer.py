from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from openai import APITimeoutError

from nxtrep_backend.agents.nutrition_vision import (
    FoodImageRecognitionError,
    FoodVisionUnavailableError,
    GlmFoodImageRecognizer,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodImageCandidate,
    FoodImageRecognitionResult,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_food_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.NUTRITION_ENTRY,
        content_type="image/jpeg",
        data=b"sanitized-food-image",
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    model = MagicMock(spec=BaseChatModel)
    model.ainvoke = AsyncMock()
    return model, model


def make_result() -> FoodImageRecognitionResult:
    return FoodImageRecognitionResult(
        foods=[
            FoodImageCandidate(
                name="熟白米饭",
                estimated_amount_g=Decimal("180"),
                amount_min_g=Decimal("150"),
                amount_max_g=Decimal("220"),
                confidence="high",
            ),
            FoodImageCandidate(
                name="鸡胸肉",
                estimated_amount_g=Decimal("120"),
                amount_min_g=Decimal("100"),
                amount_max_g=Decimal("150"),
                confidence="medium",
            ),
        ],
        assumptions=["重量均按熟重估计"],
        follow_up_questions=["烹饪时使用了多少油？"],
    )


def test_recognizer_does_not_use_unreliable_vision_tool_calling() -> None:
    model, _ = make_dependencies()

    GlmFoodImageRecognizer(model)

    model.with_structured_output.assert_not_called()


@pytest.mark.asyncio
async def test_recognizer_accepts_text_blocks_without_guessing_missing_values():
    model, _ = make_dependencies()
    expected = make_result()
    model.ainvoke.return_value = AIMessage(content=[
        {"type": "text", "text": expected.model_dump_json()},
    ])
    result = await GlmFoodImageRecognizer(model).recognize(images=[make_food_image()], notes=None)
    assert result == expected
    model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [TimeoutError(), httpx.ReadTimeout("provider response timed out")]
)
async def test_recognizer_normalizes_transport_timeout_without_reupload_or_retry(error):
    model, _ = make_dependencies()
    model.ainvoke.side_effect = error
    with pytest.raises(FoodVisionUnavailableError):
        await GlmFoodImageRecognizer(model).recognize(images=[make_food_image()], notes=None)
    model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_recognizer_returns_multiple_food_candidates() -> None:
    model, structured_model = make_dependencies()
    expected = make_result()
    structured_model.ainvoke.return_value = AIMessage(content=expected.model_dump_json())
    recognizer = GlmFoodImageRecognizer(model)

    result = await recognizer.recognize(
        images=[make_food_image()],
        notes="米饭大约一碗",
    )

    assert result == expected
    assert [food.name for food in result.foods] == ["熟白米饭", "鸡胸肉"]
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_recognizer_prompt_contains_notes_and_nutrition_boundary() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = AIMessage(content=make_result().model_dump_json())
    recognizer = GlmFoodImageRecognizer(model)

    await recognizer.recognize(
        images=[make_food_image()],
        notes="鸡肉没有放油",
    )

    messages = structured_model.ainvoke.await_args.args[0]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    prompt = messages[0].content[0]["text"]
    assert "鸡肉没有放油" in prompt
    assert "每一种" in prompt
    assert "不要计算热量" in prompt


@pytest.mark.asyncio
async def test_recognizer_reports_structured_output_parsing_failure() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = AIMessage(content="invalid food output")
    recognizer = GlmFoodImageRecognizer(model)

    with pytest.raises(FoodImageRecognitionError, match="structured output"):
        await recognizer.recognize(
            images=[make_food_image()],
            notes=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"foods":[{"name":"米饭","estimated_amount_g":0,'
        '"amount_min_g":0,"amount_max_g":0,"confidence":"low"}]}',
    ],
)
async def test_recognizer_rejects_missing_foods_or_zero_weights(raw):
    model, _ = make_dependencies()
    model.ainvoke.return_value = AIMessage(content=raw)
    with pytest.raises(FoodImageRecognitionError):
        await GlmFoodImageRecognizer(model).recognize(images=[make_food_image()], notes=None)


@pytest.mark.asyncio
async def test_recognizer_accepts_json_fence_and_explicit_no_food():
    model, _ = make_dependencies()
    model.ainvoke.return_value = AIMessage(
        content='```json\n{"foods":[],"assumptions":["照片没有食物"]}\n```'
    )
    result = await GlmFoodImageRecognizer(model).recognize(images=[make_food_image()], notes=None)
    assert result.foods == []
    assert result.assumptions == ["照片没有食物"]


@pytest.mark.asyncio
async def test_recognizer_uses_configured_single_image_fallback_when_primary_busy():
    model, _ = make_dependencies()
    busy = RuntimeError("capacity")
    busy.status_code = 429
    model.ainvoke.side_effect = busy
    fallback, _ = make_dependencies()
    fallback.ainvoke.return_value = AIMessage(content=make_result().model_dump_json())
    result = await GlmFoodImageRecognizer(model, fallback).recognize(
        images=[make_food_image()], notes=None
    )
    assert result == make_result()
    model.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_recognizer_falls_back_on_timeout_without_unbounded_retry():
    primary, _ = make_dependencies()
    primary.ainvoke.side_effect = APITimeoutError(
        request=httpx.Request("POST", "https://example.test")
    )
    fallback, _ = make_dependencies()
    fallback.ainvoke.return_value = AIMessage(content=make_result().model_dump_json())
    result = await GlmFoodImageRecognizer(primary, fallback).recognize(
        images=[make_food_image()], notes=None
    )
    assert result == make_result()
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_awaited_once()
    fallback.ainvoke.side_effect = primary.ainvoke.side_effect
    with pytest.raises(FoodVisionUnavailableError):
        await GlmFoodImageRecognizer(primary, fallback).recognize(
            images=[make_food_image()], notes=None
        )
    assert primary.ainvoke.await_count == fallback.ainvoke.await_count == 2
