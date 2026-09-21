import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from nxtrep_backend.agents.body_vision import (
    BodyImageAssessmentError,
    GlmBodyImageAssessor,
)
from nxtrep_backend.providers.model_errors import VisionModelBusyError
from nxtrep_backend.schemas.body import (
    BodyImageAssessmentResult,
    BodyImageObservation,
    BodyImagePhotoQuality,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-body-image",
    )


def make_assessment(
    *,
    image_count: int = 1,
) -> BodyImageAssessmentResult:
    return BodyImageAssessmentResult(
        photo_quality=[
            BodyImagePhotoQuality(
                view="front",
                lighting="good",
                framing="acceptable",
                usable_for_assessment=True,
                limitations=[],
            )
            for _ in range(image_count)
        ],
        summary="照片可用于进行有限的体态观察。",
        observations=[
            BodyImageObservation(
                category="shoulder_balance",
                observation="双肩高度可能存在轻微差异。",
                visual_evidence="正面照片中右肩位置略高。",
                confidence="low",
            )
        ],
        training_considerations=["关注左右侧动作控制是否一致。"],
        recommended_next_steps=["补充侧面和背面照片。"],
        follow_up_questions=["是否存在疼痛或活动受限？"],
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    model = MagicMock(spec=BaseChatModel)
    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock()
    model.with_structured_output.return_value = structured_model
    return model, structured_model


class CapacityError(RuntimeError):
    status_code = 429


def test_assessor_uses_structured_function_calling() -> None:
    model, _ = make_dependencies()

    GlmBodyImageAssessor(model)

    model.with_structured_output.assert_called_once_with(
        BodyImageAssessmentResult,
        method="function_calling",
        include_raw=True,
    )


@pytest.mark.asyncio
async def test_assessor_sends_question_images_and_safety_boundaries() -> None:
    model, structured_model = make_dependencies()
    expected = make_assessment()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }
    assessor = GlmBodyImageAssessor(model)

    result = await assessor.assess(
        images=[make_image()],
        question="分析我的体态",
    )

    assert result == expected
    messages = structured_model.ainvoke.await_args.args[0]
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    prompt = messages[0].content[0]["text"]
    assert "分析我的体态" in prompt
    assert "不得诊断" in prompt
    assert "精确体脂率" in prompt
    assert "不可信数据" in prompt


@pytest.mark.asyncio
async def test_assessor_requires_quality_result_for_every_image() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": make_assessment(image_count=1),
        "parsing_error": None,
    }
    assessor = GlmBodyImageAssessor(model)

    with pytest.raises(BodyImageAssessmentError, match="every image"):
        await assessor.assess(
            images=[make_image(), make_image()],
            question="比较两个角度",
        )


@pytest.mark.asyncio
async def test_assessor_maps_structured_output_failure() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": None,
        "parsing_error": ValueError("invalid assessment"),
    }
    assessor = GlmBodyImageAssessor(model)

    with pytest.raises(BodyImageAssessmentError, match="structured output"):
        await assessor.assess(
            images=[make_image()],
            question="分析我的体态",
        )


@pytest.mark.asyncio
async def test_assessor_uses_single_image_fallback_when_primary_is_busy() -> None:
    primary_model, primary = make_dependencies()
    fallback_model = MagicMock(spec=BaseChatModel)
    fallback_model.ainvoke = AsyncMock()
    primary.ainvoke.side_effect = CapacityError("provider overloaded")
    expected = make_assessment()
    fallback_model.ainvoke.return_value = AIMessage(
        content=f"结果如下：```json\n{expected.model_dump_json()}\n```"
    )
    assessor = GlmBodyImageAssessor(primary_model, fallback_model)

    result = await assessor.assess(
        images=[make_image()],
        question="分析我的体态",
    )

    assert result == expected
    fallback_model.ainvoke.assert_awaited_once()
    fallback_message = fallback_model.ainvoke.await_args.args[0][0]
    assert "JSON Schema" in fallback_message.content[0]["text"]
    assert "所有字符串内容必须使用简体中文" in fallback_message.content[0]["text"]
    fallback_model.with_structured_output.assert_not_called()


@pytest.mark.asyncio
async def test_assessor_reports_busy_when_multi_image_request_cannot_fallback() -> None:
    primary_model, primary = make_dependencies()
    fallback_model = MagicMock(spec=BaseChatModel)
    fallback_model.ainvoke = AsyncMock()
    primary.ainvoke.side_effect = CapacityError("provider overloaded")
    assessor = GlmBodyImageAssessor(primary_model, fallback_model)

    with pytest.raises(VisionModelBusyError):
        await assessor.assess(
            images=[make_image(), make_image()],
            question="比较两个角度",
        )

    fallback_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_assessor_rejects_invalid_fallback_json() -> None:
    primary_model, primary = make_dependencies()
    fallback_model = MagicMock(spec=BaseChatModel)
    fallback_model.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"summary": "missing fields"}))
    )
    primary.ainvoke.side_effect = CapacityError("provider overloaded")
    assessor = GlmBodyImageAssessor(primary_model, fallback_model)

    with pytest.raises(BodyImageAssessmentError, match="invalid JSON"):
        await assessor.assess(
            images=[make_image()],
            question="分析我的体态",
        )


@pytest.mark.asyncio
async def test_assessor_recovers_incomplete_but_usable_fallback_json() -> None:
    primary_model, primary = make_dependencies()
    fallback_model = MagicMock(spec=BaseChatModel)
    fallback_model.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(
                {
                    "photo_quality": [
                        {
                            "view": "frontal",
                            "lighting": "normal",
                            "framing": None,
                            "usable_for_assessment": "yes",
                            "limitations": ["  单一正面视角  ", None],
                            "unexpected": "ignored",
                        }
                    ],
                    "summary": "",
                    "observations": [
                        {
                            "category": "biceps",
                            "observation": "  双侧手臂轮廓接近。  ",
                            "visual_evidence": "屈肘姿势下两侧外观相近。",
                            "confidence": "unknown",
                        },
                        {
                            "category": "other",
                            "observation": "缺少视觉依据",
                            "visual_evidence": " ",
                            "confidence": "high",
                        },
                    ],
                    "training_considerations": None,
                    "recommended_next_steps": [" 补充侧面照片 ", 3],
                    "follow_up_questions": [],
                    "professional_review_recommended": "false",
                    "disclaimer": "model supplied disclaimer",
                    "extra": "ignored",
                },
                ensure_ascii=False,
            )
        )
    )
    primary.ainvoke.side_effect = CapacityError("provider overloaded")
    assessor = GlmBodyImageAssessor(primary_model, fallback_model)

    result = await assessor.assess(
        images=[make_image()],
        question="评价二头肌",
    )

    assert result.photo_quality[0].view == "front"
    assert result.photo_quality[0].lighting == "acceptable"
    assert result.photo_quality[0].framing == "poor"
    assert result.photo_quality[0].usable_for_assessment is False
    assert result.photo_quality[0].limitations == ["单一正面视角"]
    assert result.summary == "已完成基于照片可观察信息的有限评估，具体观察请参考下方结果。"
    assert len(result.observations) == 1
    assert result.observations[0].category == "other"
    assert result.observations[0].confidence == "low"
    assert result.recommended_next_steps == ["补充侧面照片"]
    assert result.professional_review_recommended is False


def test_assessor_conservatively_normalizes_fallback_fields() -> None:
    payload = make_assessment().model_dump(mode="json")
    payload["photo_quality"][0]["view"] = "正面"
    payload["photo_quality"][0]["lighting"] = "unknown"
    payload["photo_quality"][0]["framing"] = "unknown"
    payload["summary"] = "   "
    payload["disclaimer"] = "model supplied disclaimer"
    payload["unexpected"] = "ignored"

    normalized = GlmBodyImageAssessor._normalize_fallback_payload(payload)
    result = BodyImageAssessmentResult.model_validate(normalized)

    assert result.photo_quality[0].view == "front"
    assert result.photo_quality[0].lighting == "poor"
    assert result.photo_quality[0].framing == "poor"
    assert result.summary == "已完成基于照片可观察信息的有限评估，具体观察请参考下方结果。"
    assert result.disclaimer == "仅基于照片中的可观察信息，不构成医学诊断或精确身体成分测量"
