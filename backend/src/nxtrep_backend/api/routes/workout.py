from datetime import UTC, date, datetime, timedelta
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
from nxtrep_backend.api.routes.training import _confirmation_response
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository, WorkoutAggregate
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.workout import (
    ExpectedVersionRequest,
    ProgressionDraftCreateRequest,
    ProgressionDraftResponse,
    WorkoutAbandonRequest,
    WorkoutCreateRequest,
    WorkoutExerciseAddRequest,
    WorkoutExerciseReplaceRequest,
    WorkoutExerciseResponse,
    WorkoutExerciseSkipRequest,
    WorkoutFinishRequest,
    WorkoutFinishResponse,
    WorkoutHistoryResponse,
    WorkoutPauseRequest,
    WorkoutPreCheckUpdateRequest,
    WorkoutResponse,
    WorkoutRestTimerResponse,
    WorkoutResumeRequest,
    WorkoutRevisionResponse,
    WorkoutSetCreateRequest,
    WorkoutSetResponse,
    WorkoutSetUpdateRequest,
    WorkoutSetVoidRequest,
    WorkoutSummaryResponse,
)
from nxtrep_backend.services.workout import (
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutService,
    set_payload,
    workout_duration_seconds,
)

router = APIRouter()


def _service(session: DbSession) -> WorkoutService:
    return WorkoutService(
        SqlAlchemyWorkoutRepository(session),
        SqlAlchemyTrainingRepository(session),
        SqlAlchemyConfirmationRepository(session),
    )


def _raise_workout_error(exc: RuntimeError) -> None:
    if isinstance(exc, WorkoutNotFoundError):
        raise ApiError(status_code=404, code="WORKOUT_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, WorkoutConflictError):
        raise ApiError(
            status_code=409,
            code="WORKOUT_VERSION_CONFLICT",
            message=str(exc),
            details={"current_version": exc.current_version},
        ) from exc
    raise exc


def _set_response(item) -> WorkoutSetResponse:
    return WorkoutSetResponse.model_validate(set_payload(item))


def _workout_response(aggregate: WorkoutAggregate) -> WorkoutResponse:
    workout = aggregate.workout
    now = datetime.now(UTC)
    rest_timer = None
    if workout.status == "in_progress":
        latest = max(
            (
                (completed_set, exercise)
                for exercise in aggregate.exercises
                for completed_set in aggregate.sets_by_exercise.get(exercise.id, [])
            ),
            key=lambda pair: pair[0].completed_at,
            default=None,
        )
        if latest is not None:
            completed_set, exercise = latest
            duration = int(exercise.target_snapshot.get("rest_seconds") or 0)
            ends_at = completed_set.completed_at + timedelta(seconds=duration)
            remaining = max(0, int((ends_at - now).total_seconds()))
            if duration > 0 and remaining > 0:
                rest_timer = WorkoutRestTimerResponse(
                    workout_exercise_id=exercise.id,
                    set_id=completed_set.id,
                    duration_seconds=duration,
                    started_at=completed_set.completed_at,
                    ends_at=ends_at,
                    remaining_seconds=remaining,
                )
    return WorkoutResponse(
        id=workout.id,
        status=workout.status,
        started_at=workout.started_at,
        ended_at=workout.ended_at,
        paused_at=workout.paused_at,
        total_paused_seconds=int(workout.total_paused_seconds or 0),
        elapsed_seconds=workout_duration_seconds(workout, now),
        rest_timer=rest_timer,
        version=workout.version,
        pre_check=workout.pre_check,
        overall_difficulty=workout.overall_difficulty,
        fatigue=workout.fatigue,
        pain=workout.pain,
        interruption_reason=workout.interruption_reason,
        exercises=[
            WorkoutExerciseResponse(
                id=item.id,
                exercise_id=item.exercise_id,
                name_snapshot=item.name_snapshot,
                target_snapshot=item.target_snapshot,
                skipped=bool(item.target_snapshot.get("skipped")),
                skip_reason=item.target_snapshot.get("skip_reason"),
                sets=[_set_response(row) for row in aggregate.sets_by_exercise.get(item.id, [])],
            )
            for item in aggregate.exercises
        ],
    )


@router.post("", response_model=WorkoutResponse, status_code=201)
async def start_workout(
    body: WorkoutCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /workouts", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 201):
        return replayed
    try:
        response = _workout_response(await _service(session).create_workout(user.id, body))
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.get("/active", response_model=WorkoutResponse)
async def get_active_workout(user: CurrentUser, session: DbSession) -> WorkoutResponse:
    try:
        return _workout_response(await _service(session).get_active(user.id))
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.get("", response_model=WorkoutHistoryResponse)
async def list_workouts(
    user: CurrentUser,
    session: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> WorkoutHistoryResponse:
    if start_date and end_date and start_date > end_date:
        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )

    return await _service(session).list_history(
        user_id=user.id,
        start_date=start_date,
        end_date=end_date,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get("/{workout_id}", response_model=WorkoutResponse)
async def get_workout(workout_id: UUID, user: CurrentUser, session: DbSession) -> WorkoutResponse:
    try:
        return _workout_response(await _service(session).get_aggregate(user.id, workout_id))
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.patch("/{workout_id}/pre-check", response_model=WorkoutResponse)
async def update_workout_pre_check(
    workout_id: UUID,
    body: WorkoutPreCheckUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    try:
        return _workout_response(
            await _service(session).update_pre_check(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.post("/{workout_id}/exercises", response_model=WorkoutResponse, status_code=201)
async def add_workout_exercise(
    workout_id: UUID,
    body: WorkoutExerciseAddRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    operation = f"POST /workouts/{workout_id}/exercises"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 201):
        return replayed
    try:
        response = _workout_response(
            await _service(session).add_exercise(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post("/{workout_id}/sets", response_model=WorkoutSetResponse, status_code=201)
async def create_workout_set(
    workout_id: UUID,
    body: WorkoutSetCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutSetResponse:
    operation = f"POST /workouts/{workout_id}/sets"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutSetResponse, 201):
        return replayed
    try:
        response = _set_response(await _service(session).create_set(user.id, workout_id, body))
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.patch("/{workout_id}/sets/{set_id}", response_model=WorkoutSetResponse)
async def update_workout_set(
    workout_id: UUID,
    set_id: UUID,
    body: WorkoutSetUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutSetResponse:
    try:
        return _set_response(await _service(session).update_set(user.id, workout_id, set_id, body))
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.delete("/{workout_id}/sets/{set_id}", response_model=WorkoutSetResponse)
async def void_workout_set(
    workout_id: UUID,
    set_id: UUID,
    body: WorkoutSetVoidRequest,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutSetResponse:
    try:
        return _set_response(await _service(session).void_set(user.id, workout_id, set_id, body))
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.post("/{workout_id}/exercises/{item_id}/replace", response_model=WorkoutResponse)
async def replace_workout_exercise(
    workout_id: UUID,
    item_id: UUID,
    body: WorkoutExerciseReplaceRequest,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    try:
        return _workout_response(
            await _service(session).replace_exercise(user.id, workout_id, item_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.post("/{workout_id}/exercises/{item_id}/skip", response_model=WorkoutResponse)
async def skip_workout_exercise(
    workout_id: UUID,
    item_id: UUID,
    body: WorkoutExerciseSkipRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    operation = f"POST /workouts/{workout_id}/exercises/{item_id}/skip"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 200):
        return replayed
    try:
        response = _workout_response(
            await _service(session).skip_exercise(user.id, workout_id, item_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.post("/{workout_id}/pause", response_model=WorkoutResponse)
async def pause_workout(
    workout_id: UUID,
    body: WorkoutPauseRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    operation = f"POST /workouts/{workout_id}/pause"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 200):
        return replayed
    try:
        response = _workout_response(
            await _service(session).pause_workout(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.post("/{workout_id}/resume", response_model=WorkoutResponse)
async def resume_workout(
    workout_id: UUID,
    body: WorkoutResumeRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    operation = f"POST /workouts/{workout_id}/resume"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 200):
        return replayed
    try:
        response = _workout_response(
            await _service(session).resume_workout(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.post("/{workout_id}/abandon", response_model=WorkoutResponse)
async def abandon_workout(
    workout_id: UUID,
    body: WorkoutAbandonRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutResponse:
    operation = f"POST /workouts/{workout_id}/abandon"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutResponse, 200):
        return replayed
    try:
        response = _workout_response(
            await _service(session).abandon_workout(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.get("/{workout_id}/summary", response_model=WorkoutSummaryResponse)
async def get_workout_summary(
    workout_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutSummaryResponse:
    try:
        return WorkoutSummaryResponse.model_validate(
            await _service(session).get_summary(user.id, workout_id)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)


@router.get("/{workout_id}/revisions", response_model=list[WorkoutRevisionResponse])
async def list_workout_revisions(
    workout_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[WorkoutRevisionResponse]:
    repository = SqlAlchemyWorkoutRepository(session)
    if await repository.get_workout(user.id, workout_id) is None:
        raise ApiError(
            status_code=404,
            code="WORKOUT_NOT_FOUND",
            message="Workout not found",
        )
    rows = await repository.list_set_revisions(user.id, workout_id)
    return [WorkoutRevisionResponse.model_validate(item, from_attributes=True) for item in rows]


@router.post("/{workout_id}/finish", response_model=WorkoutFinishResponse)
async def finish_workout(
    workout_id: UUID,
    body: WorkoutFinishRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> WorkoutFinishResponse:
    operation = f"POST /workouts/{workout_id}/finish"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, WorkoutFinishResponse, 200):
        return replayed
    try:
        response = WorkoutFinishResponse.model_validate(
            await _service(session).finish_workout(user.id, workout_id, body)
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@router.post(
    "/{workout_id}/progression-drafts", response_model=ProgressionDraftResponse, status_code=201
)
async def create_progression_draft(
    workout_id: UUID,
    body: ProgressionDraftCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ProgressionDraftResponse:
    operation = f"POST /workouts/{workout_id}/progression-drafts"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ProgressionDraftResponse, 201):
        return replayed
    try:
        item = await _service(session).create_progression_draft(user.id, workout_id, body)
        response = ProgressionDraftResponse(
            id=item.id, suggestions=item.suggestions, version=item.version
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@router.post(
    "/{workout_id}/progression-drafts/{draft_id}/submit",
    response_model=ConfirmationSubmitResponse,
)
async def submit_progression_draft(
    workout_id: UUID,
    draft_id: UUID,
    body: ExpectedVersionRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /workouts/{workout_id}/progression-drafts/{draft_id}/submit"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).submit_progression(
                user.id, workout_id, draft_id, body.expected_version
            )
        )
    except RuntimeError as exc:
        _raise_workout_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response
