from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.body import (
    BodyImageAssessmentResult,
    BodyImagePhotoQuality,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.body import (
    BodyAssessmentBranchHandler,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.body_image import BodyImageWorkflow


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-body-image",
    )


def make_assessment(
    *,
    usable: bool,
) -> BodyImageAssessmentResult:
    return BodyImageAssessmentResult(
        photo_quality=[
            BodyImagePhotoQuality(
                view="front",
                lighting="good" if usable else "poor",
                framing="acceptable",
                usable_for_assessment=usable,
                limitations=([] if usable else ["光线过暗，身体轮廓不清晰"]),
            )
        ],
        summary=("照片可用于有限的体态观察。" if usable else "当前照片不适合进行可靠体态观察。"),
    )


def make_workflow() -> MagicMock:
    workflow = MagicMock(spec=BodyImageWorkflow)
    workflow.assess_resolved = AsyncMock()
    return workflow


def make_input(
    *,
    task_type: str = "body_assessment",
    images: tuple[ResolvedAgentImage, ...] = (),
    missing_fields: list[str] | None = None,
) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message="分析我的体态",
        task=AgentIntentTask(
            task_type=task_type,
            asset_ids=[image.asset_id for image in images],
            missing_fields=missing_fields or [],
            confidence="high",
            routing_reason="用户请求身体图片评估。",
        ),
        images=images,
    )


@pytest.mark.asyncio
async def test_body_handler_returns_completed_validated_assessment() -> None:
    image = make_image()
    assessment = make_assessment(usable=True)
    workflow = make_workflow()
    workflow.assess_resolved.return_value = assessment
    handler = BodyAssessmentBranchHandler(workflow)
    branch_input = make_input(images=(image,))

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert result.result == assessment.model_dump(mode="json")
    assert result.missing_fields == []
    assert result.requires_confirmation is False
    workflow.assess_resolved.assert_awaited_once_with(
        question=branch_input.message,
        images=(image,),
    )


@pytest.mark.asyncio
async def test_body_handler_requests_image_without_calling_workflow() -> None:
    workflow = make_workflow()
    handler = BodyAssessmentBranchHandler(workflow)
    branch_input = make_input(
        images=(),
        missing_fields=["photo_angle"],
    )

    result = await handler.execute(branch_input)

    assert result.status == "needs_input"
    assert result.result is None
    assert result.missing_fields == [
        "photo_angle",
        "body_images",
    ]
    workflow.assess_resolved.assert_not_awaited()


@pytest.mark.asyncio
async def test_body_handler_keeps_quality_result_and_requests_usable_image() -> None:
    image = make_image()
    assessment = make_assessment(usable=False)
    workflow = make_workflow()
    workflow.assess_resolved.return_value = assessment
    handler = BodyAssessmentBranchHandler(workflow)

    result = await handler.execute(make_input(images=(image,)))

    assert result.status == "needs_input"
    assert result.result == assessment.model_dump(mode="json")
    assert result.missing_fields == ["usable_body_image"]


@pytest.mark.asyncio
async def test_body_handler_rejects_wrong_task_type() -> None:
    workflow = make_workflow()
    handler = BodyAssessmentBranchHandler(workflow)

    with pytest.raises(ValueError, match="body_assessment task"):
        await handler.execute(make_input(task_type="nutrition_analysis"))

    workflow.assess_resolved.assert_not_awaited()
