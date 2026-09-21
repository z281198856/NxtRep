from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status
from pydantic import ValidationError

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.db.models import ExerciseContentFeedback
from nxtrep_backend.repositories.exercise import (
    ExerciseDetailRecord,
    SqlAlchemyExercisesRepository,
)
from nxtrep_backend.repositories.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.exercise import (
    ExerciseClassificationDraftRequest,
    ExerciseClassificationDraftResponse,
    ExerciseContentFeedbackRequest,
    ExerciseContentFeedbackResponse,
    ExerciseCreateRequest,
    ExerciseDetailResponse,
    ExerciseHistoryItemResponse,
    ExerciseHistoryResponse,
    ExerciseHistorySetResponse,
    ExerciseListItemResponse,
    ExerciseListQuery,
    ExerciseListResponse,
    ExerciseSubstitutionResponse,
    ExerciseUpdateRequest,
)
from nxtrep_backend.services.exercise import (
    ExerciseCreateData,
    ExerciseMuscleOverlapError,
    ExerciseNotFoundError,
    ExercisesService,
    ExerciseStateError,
    ExerciseUpdateData,
    ExerciseVersionConflictError,
)
from nxtrep_backend.services.idempotency import (
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
    IdempotencyService,
    IdempotencyStateError,
)
from nxtrep_backend.services.workout import WorkoutNotFoundError, WorkoutService

router = APIRouter()
content_router = APIRouter()

IdempotencyKey = Annotated[
    UUID,
    Header(alias="Idempotency-Key"),
]
ExpectedVersion = Annotated[
    int,
    Query(ge=1),
]


@content_router.post(
    "/{exercise_id}/feedback",
    response_model=ExerciseContentFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_exercise_content_feedback(
    exercise_id: UUID,
    body: ExerciseContentFeedbackRequest,
    user: CurrentUser,
    session: DbSession,
) -> ExerciseContentFeedbackResponse:
    repository = SqlAlchemyExercisesRepository(session)
    try:
        await ExercisesService(repository).get_exercise_detail(
            user_id=user.id, exercise_id=exercise_id
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    item = await repository.add_feedback(
        ExerciseContentFeedback(
            user_id=user.id,
            exercise_id=exercise_id,
            feedback_type=body.feedback_type,
            message=body.message.strip(),
            context=body.context,
        )
    )
    return ExerciseContentFeedbackResponse.model_validate(item, from_attributes=True)


def _build_exercise_detail_response(
    result: ExerciseDetailRecord,
) -> ExerciseDetailResponse:
    exercise = result.exercise

    return ExerciseDetailResponse(
        id=exercise.id,
        name_zh=exercise.name_zh,
        aliases=result.aliases,
        movement_pattern=exercise.movement_pattern,
        equipment=exercise.equipment,
        difficulty=exercise.difficulty,
        primary_muscles=result.primary_muscles,
        secondary_muscles=result.secondary_muscles,
        instructions=exercise.instructions,
        breathing=exercise.breathing,
        common_errors=exercise.common_errors,
        safety_notes=exercise.safety_notes,
        substitutions=[
            ExerciseSubstitutionResponse(
                id=item.exercise.id,
                name_zh=item.exercise.name_zh,
                equipment=item.exercise.equipment,
                reason=item.reason,
            )
            for item in result.substitutions
        ],
        notes=exercise.notes,
        version=exercise.version,
        is_custom=exercise.is_custom,
    )


@router.get(
    "",
    response_model=ExerciseListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_exercises(
    query: Annotated[ExerciseListQuery, Query()],
    user: CurrentUser,
    session: DbSession,
) -> ExerciseListResponse:
    repository = SqlAlchemyExercisesRepository(session)
    service = ExercisesService(repository)

    result = await service.list_exercises(
        user_id=user.id,
        keyword=query.keyword,
        equipment=query.equipment,
        muscle=query.muscle,
        page=query.page,
        page_size=query.page_size,
    )

    return ExerciseListResponse(
        list=[
            ExerciseListItemResponse(
                id=item.exercise.id,
                name_zh=item.exercise.name_zh,
                aliases=item.aliases,
                equipment=item.exercise.equipment,
                primary_muscles=item.primary_muscles,
                is_custom=item.exercise.is_custom,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@router.get(
    "/{exercise_id}",
    response_model=ExerciseDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_exercise_detail(
    exercise_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> ExerciseDetailResponse:
    repository = SqlAlchemyExercisesRepository(session)
    service = ExercisesService(repository)

    try:
        result = await service.get_exercise_detail(
            user_id=user.id,
            exercise_id=exercise_id,
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc

    return _build_exercise_detail_response(result)


@router.get(
    "/{exercise_id}/substitutions",
    response_model=list[ExerciseSubstitutionResponse],
)
async def get_exercise_substitutions(
    exercise_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[ExerciseSubstitutionResponse]:
    try:
        result = await ExercisesService(SqlAlchemyExercisesRepository(session)).get_exercise_detail(
            user_id=user.id, exercise_id=exercise_id
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    return [
        ExerciseSubstitutionResponse(
            id=item.exercise.id,
            name_zh=item.exercise.name_zh,
            equipment=item.exercise.equipment,
            reason=item.reason,
        )
        for item in result.substitutions
    ]


@router.get("/{exercise_id}/history", response_model=ExerciseHistoryResponse)
async def get_exercise_history(
    exercise_id: UUID,
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=10, ge=1, le=20),
) -> ExerciseHistoryResponse:
    service = WorkoutService(
        SqlAlchemyWorkoutRepository(session),
        SqlAlchemyTrainingRepository(session),
    )
    try:
        entries = await service.list_exercise_history(
            user_id=user.id,
            exercise_id=exercise_id,
            limit=limit,
        )
    except WorkoutNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    return ExerciseHistoryResponse(
        exercise_id=exercise_id,
        history=[
            ExerciseHistoryItemResponse(
                workout_id=entry.workout.id,
                started_at=entry.workout.started_at,
                status=entry.workout.status,
                name_snapshot=entry.exercise.name_snapshot,
                sets=[
                    ExerciseHistorySetResponse.model_validate(item, from_attributes=True)
                    for item in entry.sets
                ],
            )
            for entry in entries
        ],
    )


@router.post(
    "/{exercise_id}/classification-drafts",
    response_model=ExerciseClassificationDraftResponse,
)
async def create_exercise_classification_draft(
    exercise_id: UUID,
    body: ExerciseClassificationDraftRequest,
    user: CurrentUser,
    session: DbSession,
) -> ExerciseClassificationDraftResponse:
    try:
        detail = await ExercisesService(SqlAlchemyExercisesRepository(session)).get_exercise_detail(
            user_id=user.id, exercise_id=exercise_id
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    if not detail.exercise.is_custom:
        raise ApiError(
            status_code=409,
            code="EXERCISE_CLASSIFICATION_NOT_EDITABLE",
            message="Only custom exercises can be classified",
        )
    if detail.exercise.version != body.expected_version:
        raise ApiError(
            status_code=409,
            code="EXERCISE_VERSION_CONFLICT",
            message="Exercise has been modified",
            details={"current_version": detail.exercise.version},
        )
    return ExerciseClassificationDraftResponse(
        exercise_id=exercise_id,
        expected_version=body.expected_version,
        suggested_movement_pattern=detail.exercise.movement_pattern,
        suggested_difficulty=detail.exercise.difficulty,
        suggested_primary_muscles=detail.primary_muscles,
        suggested_secondary_muscles=detail.secondary_muscles,
        confidence="0.65" if detail.primary_muscles else "0.30",
    )


@router.post(
    "",
    response_model=ExerciseDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_exercise(
    body: ExerciseCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ExerciseDetailResponse:
    exercise_repository = SqlAlchemyExercisesRepository(session)
    exercise_service = ExercisesService(exercise_repository)

    idempotency_repository = SqlAlchemyIdempotencyRepository(session)
    idempotency_service = IdempotencyService(idempotency_repository)

    try:
        decision = await idempotency_service.begin(
            user_id=user.id,
            idempotency_key=idempotency_key,
            operation="POST /exercises",
            payload=body.model_dump(mode="json"),
        )
    except IdempotencyKeyConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_KEY_CONFLICT",
            message=("Idempotency key was reused with a different request"),
        ) from exc
    except IdempotencyRequestInProgressError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_REQUEST_IN_PROGRESS",
            message="Idempotent request is still processing",
        ) from exc
    except IdempotencyStateError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="IDEMPOTENCY_STATE_INVALID",
            message="Idempotency record state is invalid",
        ) from exc

    if decision.replayed:
        if decision.response_status != status.HTTP_201_CREATED or not isinstance(
            decision.response_body, dict
        ):
            raise ApiError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="IDEMPOTENCY_STATE_INVALID",
                message="Stored idempotency response is invalid",
            )

        try:
            return ExerciseDetailResponse.model_validate(decision.response_body)
        except ValidationError as exc:
            raise ApiError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="IDEMPOTENCY_STATE_INVALID",
                message="Stored idempotency response is invalid",
            ) from exc

    result = await exercise_service.create_custom_exercise(
        user_id=user.id,
        data=ExerciseCreateData(
            name_zh=body.name_zh,
            equipment=body.equipment,
            primary_muscles=list(body.primary_muscles),
            secondary_muscles=list(body.secondary_muscles),
            notes=body.notes,
        ),
    )
    response = _build_exercise_detail_response(result)

    await idempotency_service.complete(
        decision=decision,
        response_status=status.HTTP_201_CREATED,
        response_body=response.model_dump(mode="json"),
    )

    return response


@router.patch(
    "/{exercise_id}",
    response_model=ExerciseDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def update_custom_exercise(
    exercise_id: UUID,
    body: ExerciseUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ExerciseDetailResponse:
    repository = SqlAlchemyExercisesRepository(session)
    service = ExercisesService(repository)

    supplied_fields = frozenset(body.model_fields_set.difference({"expected_version"}))

    try:
        result = await service.update_custom_exercise(
            user_id=user.id,
            exercise_id=exercise_id,
            data=ExerciseUpdateData(
                name_zh=body.name_zh,
                equipment=body.equipment,
                primary_muscles=(
                    list(body.primary_muscles) if body.primary_muscles is not None else None
                ),
                secondary_muscles=(
                    list(body.secondary_muscles) if body.secondary_muscles is not None else None
                ),
                notes=body.notes,
                supplied_fields=supplied_fields,
            ),
            expected_version=body.expected_version,
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    except ExerciseVersionConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="EXERCISE_VERSION_CONFLICT",
            message="Exercise has been modified",
            details={
                "expected_version": exc.expected_version,
                "current_version": exc.current_version,
            },
        ) from exc
    except ExerciseMuscleOverlapError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="EXERCISE_MUSCLE_CONFLICT",
            message=("A muscle cannot be both primary and secondary"),
        ) from exc
    except ExerciseStateError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="EXERCISE_STATE_INVALID",
            message="Exercise state is invalid",
        ) from exc

    return _build_exercise_detail_response(result)


@router.delete(
    "/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_custom_exercise(
    exercise_id: UUID,
    expected_version: ExpectedVersion,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    repository = SqlAlchemyExercisesRepository(session)
    service = ExercisesService(repository)

    try:
        await service.delete_custom_exercise(
            user_id=user.id,
            exercise_id=exercise_id,
            expected_version=expected_version,
        )
    except ExerciseNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="EXERCISE_NOT_FOUND",
            message="Exercise not found",
        ) from exc
    except ExerciseVersionConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="EXERCISE_VERSION_CONFLICT",
            message="Exercise has been modified",
            details={
                "expected_version": exc.expected_version,
                "current_version": exc.current_version,
            },
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
