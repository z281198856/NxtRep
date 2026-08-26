from datetime import date
from uuid import UUID

from fastapi import APIRouter

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.api.routes.training import (
    _confirmation_response,
    _raise_training_error,
    _service,
)
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.training import (
    CalendarEventResponse,
    ExpectedVersionRequest,
    RescheduleDraftCreateRequest,
    RescheduleDraftResponse,
)

router = APIRouter()


@router.get("", response_model=list[CalendarEventResponse])
async def get_calendar(
    start_date: date, end_date: date, user: CurrentUser, session: DbSession
) -> list[CalendarEventResponse]:
    if start_date > end_date:
        from nxtrep_backend.api.errors import ApiError

        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )
    items = await SqlAlchemyTrainingRepository(session).list_calendar(user.id, start_date, end_date)
    return [CalendarEventResponse.model_validate(item, from_attributes=True) for item in items]


@router.post("/reschedule-drafts", response_model=RescheduleDraftResponse, status_code=201)
async def create_reschedule_draft(
    body: RescheduleDraftCreateRequest, user: CurrentUser, session: DbSession
) -> RescheduleDraftResponse:
    try:
        item = await _service(session).create_reschedule_draft(user.id, body)
        return RescheduleDraftResponse.model_validate(item, from_attributes=True)
    except RuntimeError as exc:
        _raise_training_error(exc)


@router.post("/reschedule-drafts/{draft_id}/submit", response_model=ConfirmationSubmitResponse)
async def submit_reschedule_draft(
    draft_id: UUID,
    body: ExpectedVersionRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /calendar/reschedule-drafts/{draft_id}/submit"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).submit_reschedule(user.id, draft_id, body.expected_version)
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response
