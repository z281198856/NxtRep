from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.body import BodyImageAssessmentResult, BodyImagePhotoQuality
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.body_progress import (
    BodyProgressComparisonBranchHandler,
)
from nxtrep_backend.services.agent_media import AgentImageAssetResolver, ResolvedAgentImage
from nxtrep_backend.services.body_image import BodyImageWorkflow
from nxtrep_backend.services.body_progress import BodyProgressPhotoService


def make_image() -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized",
    )


def make_input(user_id, images) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=user_id,
        message="和历史照片比较训练效果",
        task=AgentIntentTask(
            task_type="body_progress_comparison",
            asset_ids=[item.asset_id for item in images],
            confidence="high",
            routing_reason="compare progress",
        ),
        images=tuple(images),
    )


def make_handler():
    workflow = MagicMock(spec=BodyImageWorkflow)
    workflow.assess_resolved = AsyncMock(
        return_value=BodyImageAssessmentResult(
            photo_quality=[
                BodyImagePhotoQuality(
                    view="front",
                    lighting="good",
                    framing="good",
                    usable_for_assessment=True,
                )
            ],
            summary="照片条件可比，可观察训练变化。",
        )
    )
    progress = MagicMock(spec=BodyProgressPhotoService)
    progress.list = AsyncMock(return_value=[])
    resolver = MagicMock(spec=AgentImageAssetResolver)
    resolver.resolve = AsyncMock(return_value=[])
    handler = BodyProgressComparisonBranchHandler(workflow, progress, resolver)
    return handler, workflow, progress, resolver


@pytest.mark.asyncio
async def test_comparison_uses_saved_history_when_only_current_photo_is_uploaded() -> None:
    handler, workflow, progress, resolver = make_handler()
    user_id = uuid4()
    current = make_image()
    historical = make_image()
    progress.list.return_value = [SimpleNamespace(image_asset_id=historical.asset_id)]
    resolver.resolve.return_value = [historical]

    result = await handler.execute(make_input(user_id, [current]))

    assert result.status == "completed"
    assert result.result["comparison_order"] == [
        str(historical.asset_id),
        str(current.asset_id),
    ]
    resolver.resolve.assert_awaited_once_with(
        user_id=user_id,
        asset_ids=[historical.asset_id],
    )
    assessed_images = workflow.assess_resolved.await_args.kwargs["images"]
    assert assessed_images == (historical, current)


@pytest.mark.asyncio
async def test_comparison_requests_more_input_when_no_history_exists() -> None:
    handler, workflow, _progress, resolver = make_handler()

    result = await handler.execute(make_input(uuid4(), [make_image()]))

    assert result.status == "needs_input"
    assert result.missing_fields == ["comparison_body_images"]
    workflow.assess_resolved.assert_not_awaited()
    resolver.resolve.assert_not_awaited()
