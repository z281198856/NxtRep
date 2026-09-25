from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nxtrep_backend.agents.vision import GlmVisionAnalyzer, VisionModelResponseError
from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.core.config import StorageConfigurationError, get_settings
from nxtrep_backend.providers.model_errors import VisionModelBusyError
from nxtrep_backend.providers.models import (
    ModelConfigurationError,
    build_fallback_vision_model,
    build_vision_model,
)
from nxtrep_backend.providers.storage import StorageProviderError, build_image_storage_provider
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.training import (
    ActivePlanResponse,
    ExpectedVersionRequest,
    PlanArchiveDraftRequest,
    PlanDraftCreateRequest,
    PlanDraftFromTemplateRequest,
    PlanDraftGenerateRequest,
    PlanDraftParseImageRequest,
    PlanDraftParseTextRequest,
    PlanDraftResponse,
    PlanDraftUpdateRequest,
    PlanRevisionDraftRequest,
    PlanValidationResponse,
    PlanVersionItemResponse,
    PlanVersionListResponse,
    TrainingTemplateDetailResponse,
    TrainingTemplateResponse,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
    AgentImageAssetResolver,
)
from nxtrep_backend.services.training import (
    TrainingConflictError,
    TrainingNotFoundError,
    TrainingService,
    TrainingValidationError,
    draft_payload,
)
from nxtrep_backend.services.training_image import (
    TrainingImageReader,
    TrainingImageTranscriptionError,
)
from nxtrep_backend.services.training_text import TrainingTextParseError

router = APIRouter()


def _service(session: DbSession) -> TrainingService:
    return TrainingService(
        SqlAlchemyTrainingRepository(session), SqlAlchemyConfirmationRepository(session)
    )


def _image_reader(session: DbSession) -> TrainingImageReader:
    settings = get_settings()
    return TrainingImageReader(
        AgentImageAssetResolver(
            SqlAlchemyImageAssetRepository(session), build_image_storage_provider(settings)
        ),
        GlmVisionAnalyzer(build_vision_model(settings), build_fallback_vision_model(settings)),
    )


def _raise_training_error(exc: RuntimeError) -> None:
    if isinstance(exc, TrainingNotFoundError):
        raise ApiError(status_code=404, code="TRAINING_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, TrainingValidationError):
        raise ApiError(
            status_code=422,
            code="TRAINING_PLAN_INVALID",
            message=str(exc),
            details={"errors": exc.errors},
        ) from exc
    if isinstance(exc, TrainingConflictError):
        raise ApiError(
            status_code=409,
            code="TRAINING_VERSION_CONFLICT",
            message=str(exc),
            details={"current_version": exc.current_version},
        ) from exc
    raise exc


def _draft_response(draft) -> PlanDraftResponse:
    return PlanDraftResponse.model_validate(draft_payload(draft))


def _confirmation_response(item) -> ConfirmationSubmitResponse:
    return ConfirmationSubmitResponse(
        confirmation_id=item.id,
        operation_type=item.operation_type,
        status=item.status,
        before=item.before,
        after=item.after,
        impact=item.impact,
    )


def _plan_version_response(item) -> PlanVersionItemResponse:
    return PlanVersionItemResponse(
        id=item.id,
        plan_id=item.plan_id,
        name=item.name,
        version=item.version,
        weekly_frequency=item.weekly_frequency,
        days=item.days,
        activated_at=item.activated_at,
        status=item.status,
    )


@router.get("/templates", response_model=list[TrainingTemplateResponse])
async def list_templates(
    user: CurrentUser,
    session: DbSession,
    goal_type: str | None = None,
    days_per_week: int | None = Query(default=None, ge=1, le=7),
    equipment: str | None = None,
) -> list[TrainingTemplateResponse]:
    items = await SqlAlchemyTrainingRepository(session).list_templates(
        goal_type=goal_type, days_per_week=days_per_week, equipment=equipment
    )
    return [
        TrainingTemplateResponse(
            id=item.id,
            name=item.name,
            goal_types=item.goal_types,
            days_per_week=item.days_per_week,
            duration_minutes=item.duration_minutes,
            equipment=item.equipment,
        )
        for item in items
    ]


@router.get(
    "/templates/{template_id}",
    response_model=TrainingTemplateDetailResponse,
)
async def get_template(
    template_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> TrainingTemplateDetailResponse:
    repository = SqlAlchemyTrainingRepository(session)
    item = await repository.get_template(template_id)
    if item is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TRAINING_TEMPLATE_NOT_FOUND",
            message="Training template not found",
        )
    exercise_ids = {
        UUID(exercise["exercise_id"]) for day in item.days for exercise in day.get("exercises", [])
    }
    names = await repository.template_exercise_names(exercise_ids)
    days = [
        {
            **day,
            "exercises": [
                {**exercise, "exercise_name": names.get(exercise["exercise_id"], "动作不可用")}
                for exercise in day.get("exercises", [])
            ],
        }
        for day in item.days
    ]
    return TrainingTemplateDetailResponse(
        id=item.id,
        name=item.name,
        goal_types=item.goal_types,
        days_per_week=item.days_per_week,
        duration_minutes=item.duration_minutes,
        equipment=item.equipment,
        days=days,
    )


@router.post("/plan-drafts", response_model=PlanDraftResponse, status_code=201)
async def create_plan_draft(
    body: PlanDraftCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /training/plan-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    try:
        response = _draft_response(await _service(session).create_manual_draft(user.id, body))
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/plan-drafts/from-template", response_model=PlanDraftResponse, status_code=201)
async def create_plan_draft_from_template(
    body: PlanDraftFromTemplateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /training/plan-drafts/from-template",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    try:
        response = _draft_response(
            await _service(session).create_from_template(user.id, body.template_id, body.name)
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/plan-drafts:parse-text", response_model=PlanDraftResponse, status_code=201)
async def parse_text_plan_draft(
    body: PlanDraftParseTextRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /training/plan-drafts:parse-text",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    try:
        response = _draft_response(
            await _service(session).create_from_text(
                user_id=user.id, text=body.text, name=body.name, template_id=body.template_id
            )
        )
    except TrainingTextParseError as exc:
        raise ApiError(
            status_code=422,
            code="TRAINING_TEXT_PARSE_FAILED",
            message=str(exc),
            details={"line": exc.line},
        ) from exc
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/plan-drafts:parse-image", response_model=PlanDraftResponse, status_code=201)
async def parse_image_plan_draft(
    body: PlanDraftParseImageRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /training/plan-drafts:parse-image",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    asset = await SqlAlchemyImageAssetRepository(session).get_owned(
        user_id=user.id, asset_id=body.image_asset_id
    )
    if asset is None:
        raise ApiError(
            status_code=404,
            code="IMAGE_ASSET_NOT_FOUND",
            message="Image asset not found",
        )
    if asset.status != "ready":
        raise ApiError(
            status_code=409,
            code="IMAGE_ASSET_NOT_READY",
            message="Image asset is not ready",
        )
    if asset.purpose not in {"training_plan", "chat_attachment"}:
        raise ApiError(
            status_code=409,
            code="IMAGE_PURPOSE_INVALID",
            message="Image is not a training plan asset",
        )
    try:
        recognized_text = await _image_reader(session).read(
            user_id=user.id, asset_id=body.image_asset_id
        )
        draft = await _service(session).create_from_text(
            user_id=user.id,
            text=recognized_text,
            name=body.name,
            template_id=body.template_id,
            source="parsed_image",
        )
        response = _draft_response(draft)
        response.recognized_text = recognized_text
    except TrainingTextParseError as exc:
        raise ApiError(
            status_code=422,
            code="TRAINING_IMAGE_PARSE_FAILED",
            message=str(exc),
            details={"line": exc.line, "recognized_text": recognized_text},
        ) from exc
    except (TrainingImageTranscriptionError, VisionModelResponseError) as exc:
        raise ApiError(
            status_code=422,
            code="TRAINING_IMAGE_PARSE_FAILED",
            message=str(exc),
        ) from exc
    except (AgentImageAssetNotFoundError, AgentImageAssetNotReadyError) as exc:
        raise ApiError(status_code=409, code="IMAGE_ASSET_NOT_READY", message=str(exc)) from exc
    except VisionModelBusyError as exc:
        raise ApiError(
            status_code=503,
            code="VISION_MODEL_BUSY",
            message="AI vision service is busy; please retry shortly",
            headers={"Retry-After": "5"},
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
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/plan-drafts:generate", response_model=PlanDraftResponse, status_code=201)
async def generate_plan_draft(
    body: PlanDraftGenerateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /training/plan-drafts:generate",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    try:
        response = _draft_response(
            await _service(session).create_suggested_draft(
                user_id=user.id,
                source="generated",
                name=body.name,
                goal_type=body.goal_type,
                days_per_week=body.days_per_week,
                equipment=body.equipment,
            )
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.get("/plan-drafts/{draft_id}", response_model=PlanDraftResponse)
async def get_plan_draft(
    draft_id: UUID, user: CurrentUser, session: DbSession
) -> PlanDraftResponse:
    try:
        return _draft_response(await _service(session).get_draft(user.id, draft_id))
    except RuntimeError as exc:
        _raise_training_error(exc)


@router.patch("/plan-drafts/{draft_id}", response_model=PlanDraftResponse)
async def update_plan_draft(
    draft_id: UUID, body: PlanDraftUpdateRequest, user: CurrentUser, session: DbSession
) -> PlanDraftResponse:
    try:
        return _draft_response(await _service(session).update_draft(user.id, draft_id, body))
    except RuntimeError as exc:
        _raise_training_error(exc)


@router.delete(
    "/plan-drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_plan_draft(
    draft_id: UUID,
    expected_version: int,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    try:
        await _service(session).delete_draft(
            user_id=user.id,
            draft_id=draft_id,
            expected_version=expected_version,
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/plan-drafts/{draft_id}/validate", response_model=PlanValidationResponse)
async def validate_plan_draft(
    draft_id: UUID, body: ExpectedVersionRequest, user: CurrentUser, session: DbSession
) -> PlanValidationResponse:
    service = _service(session)
    try:
        draft = await service.get_draft(user.id, draft_id)
        if draft.version != body.expected_version:
            raise TrainingConflictError("Training plan draft was modified", draft.version)
        errors, warnings, estimated = await service.validate_draft(user.id, draft)
        return PlanValidationResponse(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            estimated_weekly_minutes=estimated,
        )
    except RuntimeError as exc:
        _raise_training_error(exc)


@router.post("/plan-drafts/{draft_id}/submit", response_model=ConfirmationSubmitResponse)
async def submit_plan_draft(
    draft_id: UUID,
    body: ExpectedVersionRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /training/plan-drafts/{draft_id}/submit"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).submit_draft(user.id, draft_id, body.expected_version)
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.get("/plans/active", response_model=ActivePlanResponse)
async def get_active_plan(user: CurrentUser, session: DbSession) -> ActivePlanResponse:
    item = await SqlAlchemyTrainingRepository(session).get_active_plan(user.id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="ACTIVE_PLAN_NOT_FOUND",
            message="No active training plan",
        )
    return ActivePlanResponse(
        id=item.id,
        plan_id=item.plan_id,
        name=item.name,
        version=item.version,
        weekly_frequency=item.weekly_frequency,
        days=item.days,
        activated_at=item.activated_at,
    )


@router.get("/plans", response_model=PlanVersionListResponse)
async def list_plans(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanVersionListResponse:
    items, total = await SqlAlchemyTrainingRepository(session).list_latest_plans(
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return PlanVersionListResponse(
        list=[_plan_version_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.get("/plans/{plan_id}", response_model=PlanVersionItemResponse)
async def get_plan(
    plan_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> PlanVersionItemResponse:
    item = await SqlAlchemyTrainingRepository(session).get_latest_plan(
        user_id=user.id,
        plan_id=plan_id,
    )
    if item is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TRAINING_PLAN_NOT_FOUND",
            message="Training plan not found",
        )
    return _plan_version_response(item)


@router.get("/plans/{plan_id}/versions", response_model=PlanVersionListResponse)
async def list_plan_versions(
    plan_id: UUID,
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PlanVersionListResponse:
    versions, total = await SqlAlchemyTrainingRepository(session).list_plan_versions(
        user.id, plan_id, page, page_size
    )
    return PlanVersionListResponse(
        list=[_plan_version_response(item) for item in versions],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.get(
    "/plans/{plan_id}/versions/{version}",
    response_model=PlanVersionItemResponse,
)
async def get_plan_version(
    plan_id: UUID,
    version: int,
    user: CurrentUser,
    session: DbSession,
) -> PlanVersionItemResponse:
    item = await SqlAlchemyTrainingRepository(session).get_plan_version_for_user(
        user_id=user.id,
        plan_id=plan_id,
        version=version,
    )
    if item is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TRAINING_PLAN_VERSION_NOT_FOUND",
            message="Training plan version not found",
        )
    return _plan_version_response(item)


@router.post(
    "/plans/{plan_id}/revision-drafts",
    response_model=PlanDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan_revision_draft(
    plan_id: UUID,
    body: PlanRevisionDraftRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> PlanDraftResponse:
    operation = f"POST /training/plans/{plan_id}/revision-drafts"
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        operation,
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, PlanDraftResponse, 201):
        return replayed
    try:
        response = _draft_response(
            await _service(session).create_revision_draft(
                user_id=user.id,
                plan_id=plan_id,
                base_version=body.base_version,
                name=body.name,
            )
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post(
    "/plans/{plan_id}/archive-drafts",
    response_model=ConfirmationSubmitResponse,
)
async def create_plan_archive_draft(
    plan_id: UUID,
    body: PlanArchiveDraftRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /training/plans/{plan_id}/archive-drafts"
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        operation,
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).create_archive_confirmation(
                user_id=user.id,
                plan_id=plan_id,
                expected_version=body.expected_version,
            )
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response
