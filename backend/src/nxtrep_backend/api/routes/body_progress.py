from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nxtrep_backend.agents.body_vision import BodyImageAssessmentError, GlmBodyImageAssessor
from nxtrep_backend.api.deps import CurrentUserId, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.config import StorageConfigurationError, get_settings
from nxtrep_backend.providers.model_errors import VisionModelBusyError
from nxtrep_backend.providers.models import (
    ModelConfigurationError,
    build_fallback_vision_model,
    build_vision_model,
)
from nxtrep_backend.providers.storage import (
    ImageValidationError,
    StorageProviderError,
    build_image_storage_provider,
)
from nxtrep_backend.repositories.body_progress import SqlAlchemyBodyProgressPhotoRepository
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.schemas.body import BodyImageAssessmentResult
from nxtrep_backend.schemas.body_progress import (
    BodyPhotoAnalysisRequest,
    BodyPhotoCompareRequest,
    BodyPhotoUploadRequest,
    BodyProgressPhotoCreateRequest,
    BodyProgressPhotoDeleteRequest,
    BodyProgressPhotoResponse,
)
from nxtrep_backend.schemas.media import ImagePurpose, ImageUploadIntentResponse
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
    AgentImageAssetResolver,
)
from nxtrep_backend.services.body_image import BodyImagePurposeError, BodyImageWorkflow
from nxtrep_backend.services.body_progress import (
    BodyProgressPhotoConflictError,
    BodyProgressPhotoNotFoundError,
    BodyProgressPhotoService,
)
from nxtrep_backend.services.media import ImageAssetService

router = APIRouter()


def _service(session: DbSession) -> BodyProgressPhotoService:
    return BodyProgressPhotoService(
        SqlAlchemyBodyProgressPhotoRepository(session),
        SqlAlchemyImageAssetRepository(session),
    )


def _raise_error(exc: RuntimeError) -> None:
    if isinstance(exc, BodyProgressPhotoNotFoundError):
        raise ApiError(
            status_code=404,
            code="BODY_PROGRESS_PHOTO_NOT_FOUND",
            message=str(exc),
        ) from exc
    if isinstance(exc, BodyProgressPhotoConflictError):
        raise ApiError(
            status_code=409,
            code="BODY_PROGRESS_PHOTO_CONFLICT",
            message=str(exc),
        ) from exc
    raise exc


def _image_workflow(session: DbSession) -> BodyImageWorkflow:
    settings = get_settings()
    return BodyImageWorkflow(
        resolver=AgentImageAssetResolver(
            SqlAlchemyImageAssetRepository(session),
            build_image_storage_provider(settings),
        ),
        assessor=GlmBodyImageAssessor(
            build_vision_model(settings),
            fallback_model=build_fallback_vision_model(settings),
        ),
    )


def _raise_vision_busy(exc: VisionModelBusyError) -> None:
    raise ApiError(
        status_code=503,
        code="VISION_MODEL_BUSY",
        message="AI vision service is busy; please retry shortly",
        headers={"Retry-After": "5"},
    ) from exc


@router.post("/uploads", response_model=ImageUploadIntentResponse, status_code=201)
async def create_body_photo_upload(
    body: BodyPhotoUploadRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ImageUploadIntentResponse:
    try:
        settings = get_settings()
        result = await ImageAssetService(
            SqlAlchemyImageAssetRepository(session),
            build_image_storage_provider(settings),
        ).create_upload_intent(
            user_id=user_id,
            purpose=ImagePurpose.BODY_PROGRESS,
            content_type=body.content_type,
            content_length=body.content_length,
        )
    except ImageValidationError as exc:
        raise ApiError(
            status_code=422,
            code="IMAGE_UPLOAD_INVALID",
            message=str(exc) or "Image upload request is invalid",
        ) from exc
    except (StorageConfigurationError, StorageProviderError) as exc:
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
    "",
    response_model=BodyProgressPhotoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_body_progress_photo(
    body: BodyProgressPhotoCreateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> BodyProgressPhotoResponse:
    try:
        item = await _service(session).create(user_id=user_id, body=body)
    except RuntimeError as exc:
        _raise_error(exc)
    return BodyProgressPhotoResponse.model_validate(item)


@router.get("", response_model=list[BodyProgressPhotoResponse])
async def list_body_progress_photos(
    user_id: CurrentUserId,
    session: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[BodyProgressPhotoResponse]:
    items = await _service(session).list(user_id=user_id, limit=limit)
    return [BodyProgressPhotoResponse.model_validate(item) for item in items]


@router.post(
    "/{photo_id}/analysis-drafts",
    response_model=BodyImageAssessmentResult,
)
async def analyze_body_progress_photo(
    photo_id: UUID,
    body: BodyPhotoAnalysisRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> BodyImageAssessmentResult:
    photo = await SqlAlchemyBodyProgressPhotoRepository(session).get_owned(
        user_id=user_id, photo_id=photo_id
    )
    if photo is None:
        raise ApiError(
            status_code=404,
            code="BODY_PROGRESS_PHOTO_NOT_FOUND",
            message="Body progress photo not found",
        )
    try:
        assessment = await _image_workflow(session).assess(
            user_id=user_id,
            question=body.question,
            asset_ids=[photo.image_asset_id],
        )
        await _service(session).save_assessment(
            user_id=user_id,
            photo_id=photo_id,
            assessment=assessment.model_dump(mode="json"),
        )
        return assessment
    except VisionModelBusyError as exc:
        _raise_vision_busy(exc)
    except (AgentImageAssetNotFoundError, AgentImageAssetNotReadyError) as exc:
        raise ApiError(status_code=409, code="BODY_IMAGE_NOT_READY", message=str(exc)) from exc
    except (BodyImagePurposeError, BodyImageAssessmentError) as exc:
        raise ApiError(
            status_code=422,
            code="BODY_IMAGE_ASSESSMENT_FAILED",
            message=str(exc),
        ) from exc
    except ModelConfigurationError as exc:
        raise ApiError(
            status_code=503,
            code="VISION_MODEL_UNAVAILABLE",
            message="Vision model is not configured",
        ) from exc
    except (StorageConfigurationError, StorageProviderError) as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc


@router.post("/compare", response_model=BodyImageAssessmentResult)
async def compare_body_progress_photos(
    body: BodyPhotoCompareRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> BodyImageAssessmentResult:
    if body.before_photo_id == body.after_photo_id:
        raise ApiError(
            status_code=422,
            code="BODY_PHOTOS_MUST_DIFFER",
            message="Two different photos are required",
        )
    repository = SqlAlchemyBodyProgressPhotoRepository(session)
    before = await repository.get_owned(user_id=user_id, photo_id=body.before_photo_id)
    after = await repository.get_owned(user_id=user_id, photo_id=body.after_photo_id)
    if before is None or after is None:
        raise ApiError(
            status_code=404,
            code="BODY_PROGRESS_PHOTO_NOT_FOUND",
            message="Body progress photo not found",
        )
    try:
        return await _image_workflow(session).assess(
            user_id=user_id,
            question=body.question,
            asset_ids=[before.image_asset_id, after.image_asset_id],
        )
    except VisionModelBusyError as exc:
        _raise_vision_busy(exc)
    except (AgentImageAssetNotFoundError, AgentImageAssetNotReadyError) as exc:
        raise ApiError(status_code=409, code="BODY_IMAGE_NOT_READY", message=str(exc)) from exc
    except (BodyImagePurposeError, BodyImageAssessmentError) as exc:
        raise ApiError(
            status_code=422,
            code="BODY_IMAGE_ASSESSMENT_FAILED",
            message=str(exc),
        ) from exc
    except ModelConfigurationError as exc:
        raise ApiError(
            status_code=503,
            code="VISION_MODEL_UNAVAILABLE",
            message="Vision model is not configured",
        ) from exc
    except (StorageConfigurationError, StorageProviderError) as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_body_progress_photo(
    photo_id: UUID,
    body: BodyProgressPhotoDeleteRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> Response:
    try:
        await _service(session).delete(
            user_id=user_id,
            photo_id=photo_id,
            expected_version=body.expected_version,
        )
    except RuntimeError as exc:
        _raise_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
