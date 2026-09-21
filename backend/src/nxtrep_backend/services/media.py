import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.providers.image_processing import (
    ImageContentValidationError,
    PillowImageContentProcessor,
)
from nxtrep_backend.providers.storage import (
    ImageStorageProvider,
    ImageValidationError,
    PresignedImageRequest,
)
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.schemas.media import ImagePurpose


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ImageUploadIntentResult:
    asset: ImageAsset
    upload: PresignedImageRequest


class ImageAssetNotFoundError(RuntimeError):
    pass


class ImageAssetStateError(RuntimeError):
    pass


class ImageUploadIntentMismatchError(RuntimeError):
    pass


class ImageAssetService:
    def __init__(
        self,
        repository: SqlAlchemyImageAssetRepository,
        storage: ImageStorageProvider,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._id_factory = id_factory
        self._clock = clock

    async def create_upload_intent(
        self,
        *,
        user_id: UUID,
        purpose: ImagePurpose,
        content_type: str,
        content_length: int,
    ) -> ImageUploadIntentResult:
        asset_id = self._id_factory()

        object_key = self._storage.create_object_key(
            user_id,
            asset_id,
            content_type,
        )

        upload = self._storage.presign_upload(
            object_key,
            content_type,
            content_length,
        )

        asset = ImageAsset(
            id=asset_id,
            user_id=user_id,
            purpose=purpose.value,
            object_key=object_key,
            content_type=content_type,
            content_length=content_length,
            status="pending_upload",
            upload_expires_at=upload.expires_at,
        )

        await self._repository.add(asset)

        return ImageUploadIntentResult(
            asset=asset,
            upload=upload,
        )

    async def complete_upload(
        self,
        *,
        user_id: UUID,
        asset_id: UUID,
        expected_content_type: str,
        expected_content_length: int,
    ) -> ImageAsset:
        asset = await self._repository.get_owned(
            user_id=user_id,
            asset_id=asset_id,
            lock=True,
        )

        if asset is None:
            raise ImageAssetNotFoundError("Image asset not found")

        if (
            expected_content_type != asset.content_type
            or expected_content_length != asset.content_length
        ):
            raise ImageUploadIntentMismatchError(
                "Upload completion metadata differs from the original intent"
            )

        if asset.status in {"uploaded", "ready"}:
            return asset

        if asset.status != "pending_upload":
            raise ImageAssetStateError(
                f"Image asset cannot be completed from status {asset.status}"
            )

        try:
            metadata = await self._storage.verify_image(
                asset.object_key,
                expected_content_type=asset.content_type,
                expected_content_length=asset.content_length,
            )
        except ImageValidationError as exc:
            asset.status = "failed"
            asset.failure_reason = str(exc)[:1000]
            await self._repository.save(asset)
            raise

        asset.status = "uploaded"
        asset.etag = metadata.etag
        asset.completed_at = self._clock()
        asset.failure_reason = None

        return await self._repository.save(asset)

    async def create_download_intent(
        self,
        *,
        user_id: UUID,
        asset_id: UUID,
    ) -> PresignedImageRequest:
        asset = await self._repository.get_owned(
            user_id=user_id,
            asset_id=asset_id,
        )

        if asset is None:
            raise ImageAssetNotFoundError("Image asset not found")
        if asset.status != "ready":
            raise ImageAssetStateError(
                f"Image asset cannot be downloaded from status {asset.status}"
            )

        return self._storage.presign_download(asset.object_key)


class ImageAssetProcessingService:
    def __init__(
        self,
        repository: SqlAlchemyImageAssetRepository,
        storage: ImageStorageProvider,
        processor: PillowImageContentProcessor,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._processor = processor

    async def process_uploaded_image(
        self,
        *,
        user_id: UUID,
        asset_id: UUID,
    ) -> ImageAsset:
        asset = await self._repository.get_owned(
            user_id=user_id,
            asset_id=asset_id,
            lock=True,
        )

        if asset is None:
            raise ImageAssetNotFoundError("Image asset not found")

        if asset.status == "ready":
            return asset

        if asset.status != "uploaded":
            raise ImageAssetStateError(
                f"Image asset cannot be processed from status {asset.status}"
            )

        original_data = await self._storage.download_image(asset.object_key)

        try:
            processed = await asyncio.to_thread(
                self._processor.process,
                original_data,
                declared_content_type=asset.content_type,
            )
        except ImageContentValidationError as exc:
            asset.status = "failed"
            asset.failure_reason = str(exc)[:1000]
            await self._repository.save(asset)
            raise

        metadata = await self._storage.replace_image(
            asset.object_key,
            processed.data,
            content_type=processed.content_type,
        )

        asset.status = "ready"
        asset.content_type = metadata.content_type
        asset.content_length = metadata.content_length
        asset.etag = metadata.etag
        asset.failure_reason = None

        return await self._repository.save(asset)
