from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.body_vision import GlmBodyImageAssessor
from nxtrep_backend.schemas.body import (
    BodyImageAssessmentResult,
    BodyImagePhotoQuality,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.body_image import (
    BodyImagePurposeError,
    BodyImageWorkflow,
)


def make_image(purpose: ImagePurpose) -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=purpose,
        content_type="image/jpeg",
        data=b"sanitized-body-image",
    )


def make_assessment() -> BodyImageAssessmentResult:
    return BodyImageAssessmentResult(
        photo_quality=[
            BodyImagePhotoQuality(
                view="front",
                lighting="good",
                framing="acceptable",
                usable_for_assessment=True,
            )
        ],
        summary="照片可用于有限的体态观察。",
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    resolver = MagicMock(spec=AgentImageAssetResolver)
    resolver.resolve = AsyncMock()
    assessor = MagicMock(spec=GlmBodyImageAssessor)
    assessor.assess = AsyncMock()
    return resolver, assessor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose",
    [
        ImagePurpose.BODY_PROGRESS,
        ImagePurpose.CHAT_ATTACHMENT,
    ],
)
async def test_workflow_resolves_allowed_images_before_assessment(
    purpose: ImagePurpose,
) -> None:
    resolver, assessor = make_dependencies()
    user_id = uuid4()
    asset_id = uuid4()
    image = make_image(purpose)
    expected = make_assessment()
    resolver.resolve.return_value = [image]
    assessor.assess.return_value = expected
    workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=assessor,
    )

    result = await workflow.assess(
        user_id=user_id,
        question="分析我的体态",
        asset_ids=[asset_id],
    )

    assert result == expected
    resolver.resolve.assert_awaited_once_with(
        user_id=user_id,
        asset_ids=[asset_id],
    )
    assessor.assess.assert_awaited_once_with(
        images=[image],
        question="分析我的体态",
    )


@pytest.mark.asyncio
async def test_workflow_rejects_nutrition_image_before_model_call() -> None:
    resolver, assessor = make_dependencies()
    resolver.resolve.return_value = [make_image(ImagePurpose.NUTRITION_ENTRY)]
    workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=assessor,
    )

    with pytest.raises(BodyImagePurposeError, match="body progress"):
        await workflow.assess(
            user_id=uuid4(),
            question="分析我的体态",
            asset_ids=[uuid4()],
        )

    assessor.assess.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_rejects_empty_asset_ids_before_resolution() -> None:
    resolver, assessor = make_dependencies()
    workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=assessor,
    )

    with pytest.raises(ValueError, match="At least one body image"):
        await workflow.assess(
            user_id=uuid4(),
            question="分析我的体态",
            asset_ids=[],
        )

    resolver.resolve.assert_not_awaited()
    assessor.assess.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolved_workflow_reuses_images_without_resolution() -> None:
    resolver, assessor = make_dependencies()
    image = make_image(ImagePurpose.BODY_PROGRESS)
    expected = make_assessment()
    assessor.assess.return_value = expected
    workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=assessor,
    )

    result = await workflow.assess_resolved(
        question="分析我的体态",
        images=[image],
    )

    assert result == expected
    resolver.resolve.assert_not_awaited()
    assessor.assess.assert_awaited_once_with(
        images=[image],
        question="分析我的体态",
    )


@pytest.mark.asyncio
async def test_resolved_workflow_rejects_empty_images() -> None:
    resolver, assessor = make_dependencies()
    workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=assessor,
    )

    with pytest.raises(ValueError, match="resolved body image"):
        await workflow.assess_resolved(
            question="分析我的体态",
            images=[],
        )

    resolver.resolve.assert_not_awaited()
    assessor.assess.assert_not_awaited()
