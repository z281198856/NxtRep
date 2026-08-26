from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status
from pydantic import ValidationError

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.repositories.exercise import (
    ExerciseDetailRecord,
    SqlAlchemyExercisesRepository,
)
from nxtrep_backend.repositories.idempotency import (
    SqlAlchemyIdempotencyRepository,
)
from nxtrep_backend.schemas.exercise import (
    ExerciseCreateRequest,
    ExerciseDetailResponse,
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

router = APIRouter()

IdempotencyKey = Annotated[
    UUID,
    Header(alias="Idempotency-Key"),
]
ExpectedVersion = Annotated[
    int,
    Query(ge=1),
]


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
    response_model=None,
    status_code=status.HTTP_200_OK,
)
async def delete_custom_exercise(
    exercise_id: UUID,
    expected_version: ExpectedVersion,
    user: CurrentUser,
    session: DbSession,
) -> None:
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

    return None
