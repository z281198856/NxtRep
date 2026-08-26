from uuid import UUID

from fastapi import APIRouter, Query, status

from nxtrep_backend.api.deps import CurrentUser, CurrentUserId, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.domain.confirmation import ConfirmationNotFoundError
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.schemas.confirmation import (
    ConfirmationApproveRequest,
    ConfirmationCreate,
    ConfirmationDecisionRequest,
    ConfirmationDecisionResponse,
    ConfirmationListItem,
    ConfirmationListResponse,
    ConfirmationRejectRequest,
    ConfirmationResponse,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
    get_confirmation_service,
)

router = APIRouter()


def _database_service(session: DbSession) -> DatabaseConfirmationService:
    return DatabaseConfirmationService(SqlAlchemyConfirmationRepository(session))


def _decision_response(item) -> ConfirmationDecisionResponse:
    return ConfirmationDecisionResponse(
        id=item.id,
        status=item.status,
        result=item.result,
        executed_at=item.executed_at,
        version=item.version,
    )


def _raise_database_error(exc: RuntimeError) -> None:
    if isinstance(exc, DatabaseConfirmationNotFoundError):
        raise ApiError(status_code=404, code="CONFIRMATION_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, DatabaseConfirmationConflictError):
        raise ApiError(
            status_code=409,
            code="CONFIRMATION_CONFLICT",
            message=str(exc),
            details={"current_version": exc.current_version},
        ) from exc
    raise exc


@router.get("", response_model=ConfirmationListResponse)
async def list_confirmations(
    user: CurrentUser,
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ConfirmationListResponse:
    items, total = await _database_service(session).list(user.id, status_filter, page, page_size)
    return ConfirmationListResponse(
        list=[ConfirmationListItem.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.post("/{confirmation_id}/approve", response_model=ConfirmationDecisionResponse)
async def approve_confirmation(
    confirmation_id: UUID,
    body: ConfirmationApproveRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationDecisionResponse:
    operation = f"POST /confirmations/{confirmation_id}/approve"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationDecisionResponse, 200):
        return replayed
    try:
        response = _decision_response(
            await _database_service(session).approve(
                user.id, confirmation_id, body.expected_version
            )
        )
    except RuntimeError as exc:
        _raise_database_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.post("/{confirmation_id}/reject", response_model=ConfirmationDecisionResponse)
async def reject_confirmation(
    confirmation_id: UUID,
    body: ConfirmationRejectRequest,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationDecisionResponse:
    try:
        return _decision_response(
            await _database_service(session).reject(
                user.id, confirmation_id, body.expected_version, body.reason
            )
        )
    except RuntimeError as exc:
        _raise_database_error(exc)


@router.post("", response_model=ConfirmationResponse, status_code=status.HTTP_201_CREATED)
async def create_confirmation(
    body: ConfirmationCreate,
    user_id: CurrentUserId,
) -> ConfirmationResponse:
    draft = await get_confirmation_service().create(user_id=user_id, data=body)
    return ConfirmationResponse.model_validate(draft)


@router.post("/{confirmation_id}/decision", response_model=ConfirmationResponse)
async def decide_confirmation(
    confirmation_id: str,
    body: ConfirmationDecisionRequest,
    user_id: CurrentUserId,
) -> ConfirmationResponse:
    try:
        draft = await get_confirmation_service().decide(
            user_id=user_id,
            confirmation_id=confirmation_id,
            decision=body.decision,
        )
    except ConfirmationNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONFIRMATION_NOT_FOUND",
            message=str(exc),
        ) from exc
    return ConfirmationResponse.model_validate(draft)
