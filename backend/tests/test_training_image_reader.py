from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.training_image import (
    TrainingImageReader,
    TrainingImageTranscriptionError,
)


@pytest.mark.asyncio
async def test_reader_sends_owned_image_bytes_to_vision_and_returns_transcription():
    user_id, asset_id = uuid4(), uuid4()
    image = ResolvedAgentImage(asset_id, ImagePurpose.TRAINING_PLAN, "image/png", b"pixels")
    resolver = AsyncMock()
    resolver.resolve.return_value = [image]
    analyzer = AsyncMock()
    analyzer.analyze.return_value = "```\n周一：哑铃地板卧推 3×8\n```"

    result = await TrainingImageReader(resolver, analyzer).read(user_id=user_id, asset_id=asset_id)

    assert result == "周一：哑铃地板卧推 3×8"
    resolver.resolve.assert_awaited_once_with(user_id=user_id, asset_ids=[asset_id])
    assert analyzer.analyze.await_args.kwargs["images"] == [image]
    assert "不要猜测" in analyzer.analyze.await_args.kwargs["question"]


@pytest.mark.asyncio
async def test_reader_rejects_empty_transcription():
    resolver = AsyncMock()
    resolver.resolve.return_value = [object()]
    analyzer = AsyncMock()
    analyzer.analyze.return_value = "  "
    with pytest.raises(TrainingImageTranscriptionError):
        await TrainingImageReader(resolver, analyzer).read(user_id=uuid4(), asset_id=uuid4())
