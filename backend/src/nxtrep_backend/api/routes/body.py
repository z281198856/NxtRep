from datetime import date
from typing import Annotated
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
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.schemas.body import (
    BodyMeasurementCreateRequest,
    BodyMeasurementListResponse,
    BodyMeasurementResponse,
    BodyMeasurementUpdateRequest,
    BodyTrendResponse,
    NavyBodyFatRequest,
    NavyBodyFatResponse,
    PersonalRecordListResponse,
    PersonalRecordResponse,
    ProgressOverviewResponse,
)
from nxtrep_backend.services.body import BodyConflictError, BodyNotFoundError, BodyService

body_router = APIRouter()
progress_router = APIRouter()
BodyMetric = Annotated[str, Query(pattern="^(weight|waist|body_fat)$")]
TrendWindow = Annotated[str, Query(pattern="^(raw|7d|14d)$")]


def _service(session: DbSession) -> BodyService:
    return BodyService(SqlAlchemyBodyRepository(session))


def _raise_body_error(exc: RuntimeError) -> None:
    if isinstance(exc, BodyNotFoundError):
        raise ApiError(
            status_code=404, code="BODY_MEASUREMENT_NOT_FOUND", message=str(exc)
        ) from exc
    if isinstance(exc, BodyConflictError):
        raise ApiError(
            status_code=409,
            code="BODY_MEASUREMENT_VERSION_CONFLICT",
            message=str(exc),
            details={"current_version": exc.current_version},
        ) from exc
    raise exc


def _measurement_response(item) -> BodyMeasurementResponse:
    return BodyMeasurementResponse.model_validate(item, from_attributes=True)


@body_router.post("/measurements", response_model=BodyMeasurementResponse, status_code=201)
async def create_body_measurement(
    body: BodyMeasurementCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> BodyMeasurementResponse:
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /body/measurements", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, BodyMeasurementResponse, 201):
        return replayed
    response = _measurement_response(await _service(session).create_measurement(user.id, body))
    await complete_idempotent(idem, decision, response, 201)
    return response


@body_router.get("/measurements", response_model=BodyMeasurementListResponse)
async def list_body_measurements(
    user: CurrentUser,
    session: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> BodyMeasurementListResponse:
    if start_date and end_date and start_date > end_date:
        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )
    items, total = await SqlAlchemyBodyRepository(session).list_measurements(
        user.id, start_date, end_date, page, page_size
    )
    return BodyMeasurementListResponse(
        list=[_measurement_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@body_router.patch("/measurements/{measurement_id}", response_model=BodyMeasurementResponse)
async def update_body_measurement(
    measurement_id: UUID,
    body: BodyMeasurementUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> BodyMeasurementResponse:
    try:
        return _measurement_response(
            await _service(session).update_measurement(user.id, measurement_id, body)
        )
    except RuntimeError as exc:
        _raise_body_error(exc)


@body_router.post("/body-fat/navy", response_model=NavyBodyFatResponse)
async def calculate_navy_body_fat(
    body: NavyBodyFatRequest, user: CurrentUser, session: DbSession
) -> NavyBodyFatResponse:
    return NavyBodyFatResponse.model_validate(await _service(session).navy_body_fat(user.id, body))


@progress_router.get("/overview", response_model=ProgressOverviewResponse)
async def get_progress_overview(
    start_date: date, end_date: date, user: CurrentUser, session: DbSession
) -> ProgressOverviewResponse:
    if start_date > end_date:
        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )
    return ProgressOverviewResponse.model_validate(
        await _service(session).overview(user.id, start_date, end_date)
    )


@progress_router.get("/body-trend", response_model=BodyTrendResponse)
async def get_body_trend(
    metric: BodyMetric,
    start_date: date,
    end_date: date,
    window: TrendWindow,
    user: CurrentUser,
    session: DbSession,
) -> BodyTrendResponse:
    if start_date > end_date:
        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )
    points = await _service(session).body_trend(user.id, metric, start_date, end_date, window)
    return BodyTrendResponse(metric=metric, window=window, points=points)


@progress_router.get("/prs", response_model=PersonalRecordListResponse)
async def list_personal_records(
    user: CurrentUser,
    session: DbSession,
    exercise_id: UUID | None = None,
    record_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PersonalRecordListResponse:
    items, total = await SqlAlchemyBodyRepository(session).list_records(
        user.id, exercise_id, record_type, page, page_size
    )
    return PersonalRecordListResponse(
        list=[
            PersonalRecordResponse(
                id=item.id,
                exercise_id=item.exercise_id,
                exercise_name=item.exercise_name_snapshot,
                record_type=item.record_type,
                value=item.value,
                occurred_at=item.occurred_at,
                workout_id=item.workout_id,
                set_id=item.set_id,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )
