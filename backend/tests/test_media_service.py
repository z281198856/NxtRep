from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.providers.storage import (
    ImageObjectMetadata,
    ImageObjectNotFoundError,
    ImageStorageProvider,
    ImageValidationError,
    PresignedImageRequest,
)
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.media import (
    ImageAssetNotFoundError,
    ImageAssetService,
    ImageAssetStateError,
    ImageUploadIntentMismatchError,
)

NOW = datetime(2026, 8, 29, 4, 0, tzinfo=UTC)


def make_asset(*, status: str = "pending_upload") -> ImageAsset:
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
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    repository = MagicMock(spec=SqlAlchemyImageAssetRepository)
    repository.add = AsyncMock()
    repository.get_owned = AsyncMock()
    repository.save = AsyncMock()
    storage = MagicMock(spec=ImageStorageProvider)
    storage.verify_image = AsyncMock()
    return repository, storage


@pytest.mark.asyncio
async def test_create_upload_intent_coordinates_identity_storage_and_database() -> None:
    repository, storage = make_dependencies()
    user_id = uuid4()
    asset_id = uuid4()
    object_key = f"images/{user_id}/{asset_id}.jpg"
    upload = PresignedImageRequest(
        object_key=object_key,
        method="PUT",
        url="https://bucket.oss-cn-hongkong.aliyuncs.com/signed-upload",
        expires_at=NOW + timedelta(minutes=10),
        headers={"Content-Type": "image/jpeg"},
    )
    storage.create_object_key.return_value = object_key
    storage.presign_upload.return_value = upload
    repository.add.side_effect = lambda asset: asset
    service = ImageAssetService(
        repository,
        storage,
        id_factory=lambda: asset_id,
        clock=lambda: NOW,
    )

    result = await service.create_upload_intent(
        user_id=user_id,
        purpose=ImagePurpose.NUTRITION_ENTRY,
        content_type="image/jpeg",
        content_length=2048,
    )

    assert result.upload is upload
    assert result.asset.id == asset_id
    assert result.asset.user_id == user_id
    assert result.asset.object_key == object_key
    assert result.asset.status == "pending_upload"
    assert result.asset.upload_expires_at == upload.expires_at
    storage.create_object_key.assert_called_once_with(user_id, asset_id, "image/jpeg")
    storage.presign_upload.assert_called_once_with(object_key, "image/jpeg", 2048)
    repository.add.assert_awaited_once_with(result.asset)


@pytest.mark.asyncio
async def test_complete_upload_verifies_stored_intent_and_marks_asset_uploaded() -> None:
    repository, storage = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    repository.save.side_effect = lambda saved: saved
    metadata = ImageObjectMetadata(
        object_key=asset.object_key,
        content_length=asset.content_length,
        content_type=asset.content_type,
        etag="test-etag",
        last_modified=NOW,
    )
    storage.verify_image.return_value = metadata
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    result = await service.complete_upload(
        user_id=asset.user_id,
        asset_id=asset.id,
        expected_content_type="image/jpeg",
        expected_content_length=2048,
    )

    assert result is asset
    assert asset.status == "uploaded"
    assert asset.etag == "test-etag"
    assert asset.completed_at == NOW
    repository.get_owned.assert_awaited_once_with(
        user_id=asset.user_id,
        asset_id=asset.id,
        lock=True,
    )
    storage.verify_image.assert_awaited_once_with(
        asset.object_key,
        expected_content_type=asset.content_type,
        expected_content_length=asset.content_length,
    )
    repository.save.assert_awaited_once_with(asset)


@pytest.mark.asyncio
async def test_complete_upload_hides_missing_or_foreign_assets() -> None:
    repository, storage = make_dependencies()
    repository.get_owned.return_value = None
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    with pytest.raises(ImageAssetNotFoundError):
        await service.complete_upload(
            user_id=uuid4(),
            asset_id=uuid4(),
            expected_content_type="image/jpeg",
            expected_content_length=2048,
        )

    storage.verify_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_upload_rejects_metadata_that_differs_from_original_intent() -> None:
    repository, storage = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    with pytest.raises(ImageUploadIntentMismatchError):
        await service.complete_upload(
            user_id=asset.user_id,
            asset_id=asset.id,
            expected_content_type="image/png",
            expected_content_length=asset.content_length,
        )

    storage.verify_image.assert_not_awaited()
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["uploaded", "ready"])
async def test_complete_upload_is_idempotent_after_upload_confirmation(status: str) -> None:
    repository, storage = make_dependencies()
    asset = make_asset(status=status)
    repository.get_owned.return_value = asset
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    result = await service.complete_upload(
        user_id=asset.user_id,
        asset_id=asset.id,
        expected_content_type=asset.content_type,
        expected_content_length=asset.content_length,
    )

    assert result is asset
    storage.verify_image.assert_not_awaited()
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_upload_rejects_terminal_asset_states() -> None:
    repository, storage = make_dependencies()
    asset = make_asset(status="deleted")
    repository.get_owned.return_value = asset
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    with pytest.raises(ImageAssetStateError):
        await service.complete_upload(
            user_id=asset.user_id,
            asset_id=asset.id,
            expected_content_type=asset.content_type,
            expected_content_length=asset.content_length,
        )

    storage.verify_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_permanent_image_validation_failure_marks_asset_failed() -> None:
    repository, storage = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    repository.save.side_effect = lambda saved: saved
    storage.verify_image.side_effect = ImageValidationError("Image size mismatch")
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    with pytest.raises(ImageValidationError):
        await service.complete_upload(
            user_id=asset.user_id,
            asset_id=asset.id,
            expected_content_type=asset.content_type,
            expected_content_length=asset.content_length,
        )

    assert asset.status == "failed"
    assert asset.failure_reason == "Image size mismatch"
    repository.save.assert_awaited_once_with(asset)


@pytest.mark.asyncio
async def test_missing_oss_object_remains_pending_so_client_can_retry() -> None:
    repository, storage = make_dependencies()
    asset = make_asset()
    repository.get_owned.return_value = asset
    storage.verify_image.side_effect = ImageObjectNotFoundError("Object not found")
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    with pytest.raises(ImageObjectNotFoundError):
        await service.complete_upload(
            user_id=asset.user_id,
            asset_id=asset.id,
            expected_content_type=asset.content_type,
            expected_content_length=asset.content_length,
        )

    assert asset.status == "pending_upload"
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_download_intent_requires_owned_ready_asset() -> None:
    repository, storage = make_dependencies()
    asset = make_asset(status="ready")
    repository.get_owned.return_value = asset
    download = PresignedImageRequest(
        object_key=asset.object_key,
        method="GET",
        url="https://bucket.oss-cn-hongkong.aliyuncs.com/signed-download",
        expires_at=NOW + timedelta(minutes=5),
        headers={},
    )
    storage.presign_download.return_value = download
    service = ImageAssetService(repository, storage, clock=lambda: NOW)

    result = await service.create_download_intent(
        user_id=asset.user_id,
        asset_id=asset.id,
    )

    assert result is download
    repository.get_owned.assert_awaited_once_with(
        user_id=asset.user_id,
        asset_id=asset.id,
    )
    storage.presign_download.assert_called_once_with(asset.object_key)


@pytest.mark.asyncio
async def test_create_download_intent_rejects_missing_or_unready_asset() -> None:
    repository, storage = make_dependencies()
    service = ImageAssetService(repository, storage, clock=lambda: NOW)
    repository.get_owned.return_value = None

    with pytest.raises(ImageAssetNotFoundError):
        await service.create_download_intent(user_id=uuid4(), asset_id=uuid4())

    repository.get_owned.return_value = make_asset(status="uploaded")
    with pytest.raises(ImageAssetStateError):
        await service.create_download_intent(user_id=uuid4(), asset_id=uuid4())

    storage.presign_download.assert_not_called()
