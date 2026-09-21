import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.body import (
    BodyImageAssessmentResult,
    BodyImageObservation,
    BodyImagePhotoQuality,
)


def make_photo_quality() -> BodyImagePhotoQuality:
    return BodyImagePhotoQuality(
        view="front",
        lighting="good",
        framing="acceptable",
        usable_for_assessment=True,
        limitations=["宽松衣物遮挡了腰部轮廓"],
    )


def test_body_image_assessment_keeps_observation_and_evidence_separate() -> None:
    result = BodyImageAssessmentResult(
        photo_quality=[make_photo_quality()],
        summary="正面照片可用于进行有限的体态观察。",
        observations=[
            BodyImageObservation(
                category="shoulder_balance",
                observation="双肩高度可能存在轻微差异。",
                visual_evidence="照片中右侧肩峰位置略高于左侧。",
                confidence="low",
            )
        ],
        training_considerations=["训练时关注左右侧动作控制是否一致。"],
        recommended_next_steps=["补充自然站立的侧面和背面照片。"],
        follow_up_questions=["是否存在疼痛或活动受限？"],
    )

    assert result.observations[0].confidence == "low"
    assert result.professional_review_recommended is False
    assert "不构成医学诊断" in result.disclaimer


def test_body_image_assessment_rejects_unapproved_extra_fields() -> None:
    with pytest.raises(ValidationError, match="body_fat_percent"):
        BodyImageAssessmentResult.model_validate(
            {
                "photo_quality": [make_photo_quality().model_dump()],
                "summary": "照片可用于有限观察。",
                "body_fat_percent": 18,
            }
        )


def test_body_image_assessment_requires_at_least_one_quality_result() -> None:
    with pytest.raises(ValidationError, match="photo_quality"):
        BodyImageAssessmentResult(
            photo_quality=[],
            summary="没有可用图片。",
        )


def test_body_image_observation_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError, match="medical_diagnosis"):
        BodyImageObservation(
            category="medical_diagnosis",
            observation="无法支持的诊断。",
            visual_evidence="无",
            confidence="low",
        )
