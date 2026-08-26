from uuid import UUID

from fastapi import APIRouter, Query

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.training import (
    ActivePlanResponse,
    ExpectedVersionRequest,
    PlanDraftCreateRequest,
    PlanDraftFromTemplateRequest,
    PlanDraftResponse,
    PlanDraftUpdateRequest,
    PlanValidationResponse,
    PlanVersionItemResponse,
    PlanVersionListResponse,
    TrainingTemplateResponse,
)
from nxtrep_backend.services.training import (
    TrainingConflictError,
    TrainingNotFoundError,
    TrainingService,
    TrainingValidationError,
    draft_payload,
)

router = APIRouter()


def _service(session: DbSession) -> TrainingService:
    return TrainingService(
        SqlAlchemyTrainingRepository(session), SqlAlchemyConfirmationRepository(session)
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
        )
        for item in items
    ]


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
        list=[
            PlanVersionItemResponse(
                id=item.id,
                plan_id=item.plan_id,
                name=item.name,
                version=item.version,
                weekly_frequency=item.weekly_frequency,
                days=item.days,
                activated_at=item.activated_at,
                status=item.status,
            )
            for item in versions
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )
