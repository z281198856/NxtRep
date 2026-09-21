from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.providers.image_processing import (
    ImageContentValidationError,
    PillowImageContentProcessor,
)
from nxtrep_backend.providers.storage import (
    AliyunOssImageStorageProvider,
    ImageObjectNotFoundError,
    ImageStorageProvider,
    ImageValidationError,
    StorageProviderError,
)
from nxtrep_backend.repositories.media import (
    SqlAlchemyImageAssetRepository,
)
from nxtrep_backend.schemas.media import (
    ImageAssetResponse,
    ImageDownloadIntentResponse,
    ImageUploadCapabilitiesResponse,
    ImageUploadCompleteRequest,
    ImageUploadIntentRequest,
    ImageUploadIntentResponse,
)
from nxtrep_backend.services.media import (
    ImageAssetNotFoundError,
    ImageAssetProcessingService,
    ImageAssetService,
    ImageAssetStateError,
    ImageUploadIntentMismatchError,
)

router = APIRouter()


@lru_cache
def get_image_storage_provider() -> ImageStorageProvider:
    settings = get_settings()
    configuration = settings.require_oss_configuration()
    return AliyunOssImageStorageProvider(configuration)


@lru_cache
def get_image_content_processor() -> PillowImageContentProcessor:
    settings = get_settings()

    return PillowImageContentProcessor(
        max_input_bytes=settings.image_max_bytes,
        max_output_bytes=settings.image_max_bytes,
        max_pixels=settings.image_max_pixels,
        max_dimension=settings.image_max_dimension,
    )


ImageStorage = Annotated[
    ImageStorageProvider,
    Depends(get_image_storage_provider),
]

ImageProcessor = Annotated[
    PillowImageContentProcessor,
    Depends(get_image_content_processor),
]


@router.get(
    "/images/capabilities",
    response_model=ImageUploadCapabilitiesResponse,
)
async def get_image_upload_capabilities(
    _: CurrentUser,
) -> ImageUploadCapabilitiesResponse:
    settings = get_settings()
    return ImageUploadCapabilitiesResponse(
        accepted_content_types=["image/jpeg", "image/png", "image/webp"],
        preferred_content_type="image/jpeg",
        convert_before_upload=["image/heic", "image/heif"],
        max_bytes=settings.image_max_bytes,
        max_pixels=settings.image_max_pixels,
        max_dimension=settings.image_max_dimension,
        direct_upload_method="PUT",
        upload_url_expires_in=settings.oss_upload_url_expire_seconds,
    )


@router.post(
    "/images/upload-intents",
    response_model=ImageUploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_image_upload_intent(
    body: ImageUploadIntentRequest,
    user: CurrentUser,
    session: DbSession,
    storage: ImageStorage,
) -> ImageUploadIntentResponse:
    repository = SqlAlchemyImageAssetRepository(session)
    service = ImageAssetService(repository, storage)

    try:
        result = await service.create_upload_intent(
            user_id=user.id,
            purpose=body.purpose,
            content_type=body.content_type,
            content_length=body.content_length,
        )
    except ImageValidationError as exc:
        raise ApiError(
            status_code=422,
            code="IMAGE_UPLOAD_INVALID",
            message=str(exc) or "Image upload request is invalid",
        ) from exc
    except StorageProviderError as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc

    return ImageUploadIntentResponse(
        asset_id=result.asset.id,
        method=result.upload.method,
        upload_url=result.upload.url,
        headers=dict(result.upload.headers),
        expires_at=result.upload.expires_at,
        status=result.asset.status,
    )


@router.post(
    "/images/{asset_id}/complete",
    response_model=ImageAssetResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_image_upload(
    asset_id: UUID,
    body: ImageUploadCompleteRequest,
    user: CurrentUser,
    session: DbSession,
    storage: ImageStorage,
    processor: ImageProcessor,
) -> ImageAssetResponse:
    repository = SqlAlchemyImageAssetRepository(session)

    upload_service = ImageAssetService(
        repository,
        storage,
    )
    processing_service = ImageAssetProcessingService(
        repository,
        storage,
        processor,
    )

    try:
        await upload_service.complete_upload(
            user_id=user.id,
            asset_id=asset_id,
            expected_content_type=body.expected_content_type,
            expected_content_length=body.expected_content_length,
        )

        asset = await processing_service.process_uploaded_image(
            user_id=user.id,
            asset_id=asset_id,
        )
    except ImageAssetNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="IMAGE_ASSET_NOT_FOUND",
            message="Image asset not found",
        ) from exc
    except ImageUploadIntentMismatchError as exc:
        raise ApiError(
            status_code=409,
            code="IMAGE_UPLOAD_MISMATCH",
            message="Upload metadata differs from the original intent",
        ) from exc
    except ImageAssetStateError as exc:
        raise ApiError(
            status_code=409,
            code="IMAGE_ASSET_STATE_INVALID",
            message=str(exc) or "Image asset state is invalid",
        ) from exc
    except ImageObjectNotFoundError as exc:
        raise ApiError(
            status_code=409,
            code="IMAGE_UPLOAD_NOT_FOUND",
            message="Uploaded image was not found in object storage",
        ) from exc
    except ImageContentValidationError as exc:
        raise ApiError(
            status_code=422,
            code="IMAGE_CONTENT_INVALID",
            message=str(exc) or "Image content is invalid",
        ) from exc
    except ImageValidationError as exc:
        raise ApiError(
            status_code=422,
            code="IMAGE_UPLOAD_INVALID",
            message=str(exc) or "Uploaded image is invalid",
        ) from exc
    except StorageProviderError as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc

    return ImageAssetResponse.model_validate(
        asset,
        from_attributes=True,
    )


@router.get(
    "/images/{asset_id}/download-intent",
    response_model=ImageDownloadIntentResponse,
)
async def create_image_download_intent(
    asset_id: UUID,
    user: CurrentUser,
    session: DbSession,
    storage: ImageStorage,
) -> ImageDownloadIntentResponse:
    service = ImageAssetService(SqlAlchemyImageAssetRepository(session), storage)
    try:
        download = await service.create_download_intent(
            user_id=user.id,
            asset_id=asset_id,
        )
    except ImageAssetNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="IMAGE_ASSET_NOT_FOUND",
            message="Image asset not found",
        ) from exc
    except ImageAssetStateError as exc:
        raise ApiError(
            status_code=409,
            code="IMAGE_ASSET_STATE_INVALID",
            message=str(exc) or "Image asset state is invalid",
        ) from exc
    except StorageProviderError as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc

    return ImageDownloadIntentResponse(
        method="GET",
        download_url=download.url,
        headers=dict(download.headers),
        expires_at=download.expires_at,
    )
