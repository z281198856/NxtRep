from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
    AgentImageAssetResolver,
)

from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.providers.storage import ImageStorageProvider, StorageProviderError
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository

NOW = datetime(2026, 8, 29, 7, 0, tzinfo=UTC)


def make_asset(
    *,
    user_id,
    purpose: str = "body_progress",
    status: str = "ready",
) -> ImageAsset:
    asset_id = uuid4()
    return ImageAsset(
        id=asset_id,
        user_id=user_id,
        purpose=purpose,
        object_key=f"images/{user_id}/{asset_id}.jpg",
        content_type="image/jpeg",
        content_length=2048,
        status=status,
        upload_expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
        completed_at=NOW,
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    repository = MagicMock(spec=SqlAlchemyImageAssetRepository)
    repository.get_owned = AsyncMock()

    storage = MagicMock(spec=ImageStorageProvider)
    storage.download_image = AsyncMock()
    return repository, storage


@pytest.mark.asyncio
async def test_resolver_returns_owned_ready_images_in_request_order() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    body_asset = make_asset(user_id=user_id)
    food_asset = make_asset(user_id=user_id, purpose="nutrition_entry")
    repository.get_owned.side_effect = [body_asset, food_asset]
    storage.download_image.side_effect = [b"body-image", b"food-image"]
    resolver = AgentImageAssetResolver(repository, storage)

    result = await resolver.resolve(
        user_id=user_id,
        asset_ids=[body_asset.id, food_asset.id],
    )

    assert [item.asset_id for item in result] == [body_asset.id, food_asset.id]
    assert [item.purpose for item in result] == ["body_progress", "nutrition_entry"]
    assert [item.content_type for item in result] == ["image/jpeg", "image/jpeg"]
    assert [item.data for item in result] == [b"body-image", b"food-image"]
    assert repository.get_owned.await_args_list[0].kwargs == {
        "user_id": user_id,
        "asset_id": body_asset.id,
    }
    assert repository.get_owned.await_args_list[1].kwargs == {
        "user_id": user_id,
        "asset_id": food_asset.id,
    }


@pytest.mark.asyncio
async def test_resolver_returns_empty_without_touching_dependencies() -> None:
    repository, storage = make_dependencies()
    resolver = AgentImageAssetResolver(repository, storage)

    result = await resolver.resolve(user_id=uuid4(), asset_ids=[])

    assert result == []
    repository.get_owned.assert_not_awaited()
    storage.download_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_hides_missing_or_foreign_image_assets() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    asset_id = uuid4()
    repository.get_owned.return_value = None
    resolver = AgentImageAssetResolver(repository, storage)

    with pytest.raises(AgentImageAssetNotFoundError):
        await resolver.resolve(user_id=user_id, asset_ids=[asset_id])

    storage.download_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_rejects_image_that_is_not_ready() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    asset = make_asset(user_id=user_id, status="uploaded")
    repository.get_owned.return_value = asset
    resolver = AgentImageAssetResolver(repository, storage)

    with pytest.raises(AgentImageAssetNotReadyError):
        await resolver.resolve(user_id=user_id, asset_ids=[asset.id])

    storage.download_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_validates_every_asset_before_downloading_any() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    ready_asset = make_asset(user_id=user_id)
    missing_asset_id = uuid4()
    repository.get_owned.side_effect = [ready_asset, None]
    resolver = AgentImageAssetResolver(repository, storage)

    with pytest.raises(AgentImageAssetNotFoundError):
        await resolver.resolve(
            user_id=user_id,
            asset_ids=[ready_asset.id, missing_asset_id],
        )

    storage.download_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_propagates_transient_storage_failure() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    asset = make_asset(user_id=user_id)
    repository.get_owned.return_value = asset
    storage.download_image.side_effect = StorageProviderError("OSS unavailable")
    resolver = AgentImageAssetResolver(repository, storage)

    with pytest.raises(StorageProviderError):
        await resolver.resolve(user_id=user_id, asset_ids=[asset.id])
