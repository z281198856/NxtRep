from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.agent_vision import AgentVisionContextService


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    resolver = MagicMock(spec=AgentImageAssetResolver)
    resolver.resolve = AsyncMock()

    analyzer = MagicMock(spec=GlmVisionAnalyzer)
    analyzer.analyze = AsyncMock()
    return resolver, analyzer


@pytest.mark.asyncio
async def test_text_only_request_skips_image_resolution_and_vision_model() -> None:
    resolver, analyzer = make_dependencies()
    service = AgentVisionContextService(resolver, analyzer)

    result = await service.build_context(
        user_id=uuid4(),
        question="帮我设计今天的训练",
        asset_ids=[],
    )

    assert result is None
    resolver.resolve.assert_not_awaited()
    analyzer.analyze.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_request_resolves_assets_before_vision_analysis() -> None:
    resolver, analyzer = make_dependencies()
    user_id = uuid4()
    asset_id = uuid4()
    image = ResolvedAgentImage(
        asset_id=asset_id,
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-image",
    )
    resolver.resolve.return_value = [image]
    analyzer.analyze.return_value = "观察到左右肩高度可能存在轻微差异。"
    service = AgentVisionContextService(resolver, analyzer)

    result = await service.build_context(
        user_id=user_id,
        question="分析我的体态",
        asset_ids=[asset_id],
    )

    assert result == "观察到左右肩高度可能存在轻微差异。"
    resolver.resolve.assert_awaited_once_with(
        user_id=user_id,
        asset_ids=[asset_id],
    )
    analyzer.analyze.assert_awaited_once_with(
        question="分析我的体态",
        images=[image],
    )
