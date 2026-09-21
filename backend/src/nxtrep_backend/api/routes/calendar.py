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
    CalendarEventCreateRequest,
    CalendarEventDetailResponse,
    CalendarEventResponse,
    CompressionDraftCreateRequest,
    ExpectedVersionRequest,
    RescheduleDraftCreateRequest,
    RescheduleDraftResponse,
    SubstitutionDraftCreateRequest,
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


@router.get("/events/{event_id}", response_model=CalendarEventDetailResponse)
async def get_calendar_event(
    event_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> CalendarEventDetailResponse:
    item = await SqlAlchemyTrainingRepository(session).get_calendar_event(user.id, event_id)
    if item is None:
        from nxtrep_backend.api.errors import ApiError

        raise ApiError(status_code=404, code="CALENDAR_EVENT_NOT_FOUND", message="Event not found")
    return CalendarEventDetailResponse.model_validate(item, from_attributes=True)


@router.post("/events", response_model=CalendarEventDetailResponse, status_code=201)
async def create_calendar_event(
    body: CalendarEventCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> CalendarEventDetailResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /calendar/events",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, CalendarEventDetailResponse, 201):
        return replayed
    try:
        item = await _service(session).create_manual_calendar_event(
            user_id=user.id,
            scheduled_date=body.scheduled_date,
            title=body.title,
            estimated_minutes=body.estimated_minutes,
            exercises=[exercise.model_dump(mode="json") for exercise in body.exercises],
        )
        response = CalendarEventDetailResponse.model_validate(item, from_attributes=True)
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/reschedule-drafts", response_model=RescheduleDraftResponse, status_code=201)
async def create_reschedule_draft(
    body: RescheduleDraftCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> RescheduleDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /calendar/reschedule-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, RescheduleDraftResponse, 201):
        return replayed
    try:
        item = await _service(session).create_reschedule_draft(user.id, body)
        response = RescheduleDraftResponse.model_validate(item, from_attributes=True)
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/compression-drafts", response_model=RescheduleDraftResponse, status_code=201)
async def create_compression_draft(
    body: CompressionDraftCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> RescheduleDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /calendar/compression-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, RescheduleDraftResponse, 201):
        return replayed
    try:
        response = RescheduleDraftResponse.model_validate(
            await _service(session).create_compression_draft(user.id, body),
            from_attributes=True,
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/substitution-drafts", response_model=RescheduleDraftResponse, status_code=201)
async def create_substitution_draft(
    body: SubstitutionDraftCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> RescheduleDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /calendar/substitution-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, RescheduleDraftResponse, 201):
        return replayed
    try:
        response = RescheduleDraftResponse.model_validate(
            await _service(session).create_substitution_draft(user.id, body),
            from_attributes=True,
        )
    except RuntimeError as exc:
        _raise_training_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.get("/reschedule-drafts/{draft_id}", response_model=RescheduleDraftResponse)
async def get_reschedule_draft(
    draft_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> RescheduleDraftResponse:
    item = await SqlAlchemyTrainingRepository(session).get_reschedule_draft(user.id, draft_id)
    if item is None:
        from nxtrep_backend.api.errors import ApiError

        raise ApiError(
            status_code=404,
            code="RESCHEDULE_DRAFT_NOT_FOUND",
            message="Reschedule draft not found",
        )
    return RescheduleDraftResponse.model_validate(item, from_attributes=True)


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
