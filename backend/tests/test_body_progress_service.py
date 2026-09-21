from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.repositories.body_progress import SqlAlchemyBodyProgressPhotoRepository
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.schemas.body_progress import BodyProgressPhotoCreateRequest
from nxtrep_backend.services.body_progress import (
    BodyProgressPhotoConflictError,
    BodyProgressPhotoNotFoundError,
    BodyProgressPhotoService,
)


def make_service():
    photos = MagicMock(spec=SqlAlchemyBodyProgressPhotoRepository)
    photos.get_by_asset = AsyncMock(return_value=None)
    photos.add = AsyncMock(side_effect=lambda item: item)
    images = MagicMock(spec=SqlAlchemyImageAssetRepository)
    images.get_owned = AsyncMock()
    return BodyProgressPhotoService(photos, images), photos, images


@pytest.mark.asyncio
async def test_create_progress_photo_requires_ready_body_image() -> None:
    service, photos, images = make_service()
    images.get_owned.return_value = SimpleNamespace(
        status="ready",
        purpose="body_progress",
    )
    request = BodyProgressPhotoCreateRequest(
        image_asset_id=uuid4(),
        captured_at=datetime(2026, 9, 8, tzinfo=UTC),
        view="front",
    )

    result = await service.create(user_id=uuid4(), body=request)

    assert result.image_asset_id == request.image_asset_id
    assert result.view == "front"
    photos.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_progress_photo_rejects_nutrition_image() -> None:
    service, photos, images = make_service()
    images.get_owned.return_value = SimpleNamespace(
        status="ready",
        purpose="nutrition_entry",
    )

    with pytest.raises(BodyProgressPhotoConflictError, match="not a body"):
        await service.create(
            user_id=uuid4(),
            body=BodyProgressPhotoCreateRequest(
                image_asset_id=uuid4(),
                captured_at=datetime(2026, 9, 8, tzinfo=UTC),
            ),
        )

    photos.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_assessment_persists_result_and_advances_version() -> None:
    service, photos, _images = make_service()
    item = SimpleNamespace(assessment=None, version=1)
    photos.get_owned = AsyncMock(return_value=item)
    photos.flush = AsyncMock()
    user_id = uuid4()
    photo_id = uuid4()
    assessment = {"summary": "变化稳定"}

    result = await service.save_assessment(
        user_id=user_id,
        photo_id=photo_id,
        assessment=assessment,
    )

    assert result is item
    assert item.assessment == assessment
    assert item.version == 2
    photos.get_owned.assert_awaited_once_with(
        user_id=user_id,
        photo_id=photo_id,
        lock=True,
    )
    photos.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_assessment_rejects_missing_photo() -> None:
    service, photos, _images = make_service()
    photos.get_owned = AsyncMock(return_value=None)

    with pytest.raises(BodyProgressPhotoNotFoundError):
        await service.save_assessment(
            user_id=uuid4(),
            photo_id=uuid4(),
            assessment={"summary": "missing"},
        )
