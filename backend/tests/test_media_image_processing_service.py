from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.providers.image_processing import (
    ImageContentValidationError,
    PillowImageContentProcessor,
    ProcessedImage,
)
from nxtrep_backend.providers.storage import (
    ImageObjectMetadata,
    ImageStorageProvider,
    StorageProviderError,
)
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.services.media import (
    ImageAssetNotFoundError,
    ImageAssetProcessingService,
    ImageAssetStateError,
)

NOW = datetime(2026, 8, 29, 5, 0, tzinfo=UTC)


def make_asset(*, status: str = "uploaded") -> ImageAsset:
    user_id = uuid4()
    asset_id = uuid4()
    return ImageAsset(
        id=asset_id,
        user_id=user_id,
        purpose="nutrition_entry",
        object_key=f"images/{user_id}/{asset_id}.jpg",
        content_type="image/jpeg",
        content_length=2048,
        status=status,
        upload_expires_at=NOW + timedelta(minutes=10),
        etag="original-etag",
        completed_at=NOW,
    )


def make_dependencies() -> tuple[MagicMock, MagicMock, MagicMock]:
    repository = MagicMock(spec=SqlAlchemyImageAssetRepository)
    repository.get_owned = AsyncMock()
    repository.save = AsyncMock()

    storage = MagicMock(spec=ImageStorageProvider)
    storage.download_image = AsyncMock()
    storage.replace_image = AsyncMock()

    processor = MagicMock(spec=PillowImageContentProcessor)
    return repository, storage, processor


@pytest.mark.asyncio
async def test_process_uploaded_image_sanitizes_storage_and_marks_asset_ready() -> None:
    repository, storage, processor = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    repository.save.side_effect = lambda saved: saved
    storage.download_image.return_value = b"original-image"
    processor.process.return_value = ProcessedImage(
        data=b"sanitized-image",
        content_type="image/jpeg",
        width=800,
        height=1200,
    )
    storage.replace_image.return_value = ImageObjectMetadata(
        object_key=asset.object_key,
        content_length=len(b"sanitized-image"),
        content_type="image/jpeg",
        etag="sanitized-etag",
        last_modified=NOW,
    )
    service = ImageAssetProcessingService(repository, storage, processor)

    result = await service.process_uploaded_image(
        user_id=asset.user_id,
        asset_id=asset.id,
    )

    assert result is asset
    assert asset.status == "ready"
    assert asset.content_type == "image/jpeg"
    assert asset.content_length == len(b"sanitized-image")
    assert asset.etag == "sanitized-etag"
    assert asset.failure_reason is None
    repository.get_owned.assert_awaited_once_with(
        user_id=asset.user_id,
        asset_id=asset.id,
        lock=True,
    )
    storage.download_image.assert_awaited_once_with(asset.object_key)
    processor.process.assert_called_once_with(
        b"original-image",
        declared_content_type="image/jpeg",
    )
    storage.replace_image.assert_awaited_once_with(
        asset.object_key,
        b"sanitized-image",
        content_type="image/jpeg",
    )
    repository.save.assert_awaited_once_with(asset)


@pytest.mark.asyncio
async def test_process_uploaded_image_hides_missing_or_foreign_assets() -> None:
    repository, storage, processor = make_dependencies()
    repository.get_owned.return_value = None
    service = ImageAssetProcessingService(repository, storage, processor)

    with pytest.raises(ImageAssetNotFoundError):
        await service.process_uploaded_image(
            user_id=uuid4(),
            asset_id=uuid4(),
        )

    storage.download_image.assert_not_awaited()
    processor.process.assert_not_called()


@pytest.mark.asyncio
async def test_process_uploaded_image_is_idempotent_when_already_ready() -> None:
    repository, storage, processor = make_dependencies()
    asset = make_asset(status="ready")
    repository.get_owned.return_value = asset
    service = ImageAssetProcessingService(repository, storage, processor)

    result = await service.process_uploaded_image(
        user_id=asset.user_id,
        asset_id=asset.id,
    )

    assert result is asset
    storage.download_image.assert_not_awaited()
    processor.process.assert_not_called()
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_upload", "failed", "deleted"])
async def test_process_uploaded_image_rejects_invalid_states(status: str) -> None:
    repository, storage, processor = make_dependencies()
    asset = make_asset(status=status)
    repository.get_owned.return_value = asset
    service = ImageAssetProcessingService(repository, storage, processor)

    with pytest.raises(ImageAssetStateError):
        await service.process_uploaded_image(
            user_id=asset.user_id,
            asset_id=asset.id,
        )

    storage.download_image.assert_not_awaited()
    processor.process.assert_not_called()
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_image_content_marks_asset_failed() -> None:
    repository, storage, processor = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    repository.save.side_effect = lambda saved: saved
    storage.download_image.return_value = b"not-an-image"
    processor.process.side_effect = ImageContentValidationError(
        "Image content could not be safely decoded"
    )
    service = ImageAssetProcessingService(repository, storage, processor)

    with pytest.raises(ImageContentValidationError):
        await service.process_uploaded_image(
            user_id=asset.user_id,
            asset_id=asset.id,
        )

    assert asset.status == "failed"
    assert asset.failure_reason == "Image content could not be safely decoded"
    storage.replace_image.assert_not_awaited()
    repository.save.assert_awaited_once_with(asset)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["download", "replace"])
async def test_transient_storage_failure_keeps_asset_uploaded_for_retry(
    failure_stage: str,
) -> None:
    repository, storage, processor = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    storage.download_image.return_value = b"original-image"
    processor.process.return_value = ProcessedImage(
        data=b"sanitized-image",
        content_type="image/jpeg",
        width=800,
        height=1200,
    )

    if failure_stage == "download":
        storage.download_image.side_effect = StorageProviderError("OSS unavailable")
    else:
        storage.replace_image.side_effect = StorageProviderError("OSS unavailable")

    service = ImageAssetProcessingService(repository, storage, processor)

    with pytest.raises(StorageProviderError):
        await service.process_uploaded_image(
            user_id=asset.user_id,
            asset_id=asset.id,
        )

    assert asset.status == "uploaded"
    assert asset.failure_reason is None
    repository.save.assert_not_awaited()
