from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from nxtrep_backend.agents.nutrition_vision import (
    FoodImageRecognitionError,
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
    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock()
    model.with_structured_output.return_value = structured_model
    return model, structured_model


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


def test_recognizer_configures_function_calling_structured_output() -> None:
    model, _ = make_dependencies()

    GlmFoodImageRecognizer(model)

    model.with_structured_output.assert_called_once_with(
        FoodImageRecognitionResult,
        method="function_calling",
        include_raw=True,
    )


@pytest.mark.asyncio
async def test_recognizer_returns_multiple_food_candidates() -> None:
    model, structured_model = make_dependencies()
    expected = make_result()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }
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
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": make_result(),
        "parsing_error": None,
    }
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
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": None,
        "parsing_error": ValueError("invalid food output"),
    }
    recognizer = GlmFoodImageRecognizer(model)

    with pytest.raises(FoodImageRecognitionError, match="structured output"):
        await recognizer.recognize(
            images=[make_food_image()],
            notes=None,
        )
