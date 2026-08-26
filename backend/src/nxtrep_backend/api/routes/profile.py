from fastapi import APIRouter, status

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.repositories.goals import (
    SqlAlchemyGoalsRepository,
)
from nxtrep_backend.repositories.profile import (
    SqlAlchemyProfileRepository,
)
from nxtrep_backend.schemas.goals import (
    ConstraintsResponse,
    GoalsAndConstraintsResponse,
    GoalsAndConstraintsUpdateRequest,
)
from nxtrep_backend.schemas.profile import (
    ProfileResponse,
    ProfileUpdateRequest,
)
from nxtrep_backend.services.goals import (
    GoalsExerciseUnavailableError,
    GoalsNotFoundError,
    GoalsService,
    GoalsStateError,
    GoalsUpdateData,
    GoalsUpdateResult,
    GoalsVersionConflictError,
    GoalsVersionRequiredError,
)
from nxtrep_backend.services.profile import (
    ProfileNotFoundError,
    ProfileService,
    ProfileVersionConflictError,
)

router = APIRouter()


def _build_goals_response(
    result: GoalsUpdateResult,
) -> GoalsAndConstraintsResponse:
    constraints = result.constraints

    return GoalsAndConstraintsResponse(
        version=result.goal.version,
        goal=result.goal,
        constraints=ConstraintsResponse(
            equipment=constraints.equipment,
            preferred_exercises=(constraints.preferred_exercise_ids),
            disliked_exercises=(constraints.disliked_exercise_ids),
            pain_or_injuries=(constraints.pain_or_injuries),
            allergies=constraints.allergies,
            dietary_preferences=(constraints.dietary_preferences),
        ),
        warnings=result.warnings,
    )


@router.get(
    "",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
)
async def get_profile(
    user: CurrentUser,
) -> ProfileResponse:
    if user.profile is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="PROFILE_NOT_FOUND",
            message="Profile not found",
        )

    return ProfileResponse.model_validate(user.profile)


@router.patch(
    "",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
)
async def update_profile(
    body: ProfileUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ProfileResponse:
    changes = body.model_dump(
        exclude_unset=True,
        exclude={"expected_version"},
    )

    repository = SqlAlchemyProfileRepository(session)
    service = ProfileService(repository)

    try:
        profile = await service.update_profile(
            user_id=user.id,
            changes=changes,
            expected_version=body.expected_version,
        )
    except ProfileNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="PROFILE_NOT_FOUND",
            message="Profile not found",
        ) from exc
    except ProfileVersionConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="PROFILE_VERSION_CONFLICT",
            message="Profile has been modified",
            details={
                "expected_version": exc.expected_version,
                "current_version": exc.current_version,
            },
        ) from exc

    return ProfileResponse.model_validate(profile)


@router.get(
    "/goals-and-constraints",
    response_model=GoalsAndConstraintsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_goals_and_constraints(
    user: CurrentUser,
    session: DbSession,
) -> GoalsAndConstraintsResponse:
    repository = SqlAlchemyGoalsRepository(session)
    service = GoalsService(repository)

    try:
        result = await service.get_goals_and_constraints(
            user_id=user.id,
        )
    except GoalsNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="GOALS_NOT_FOUND",
            message="Goals and constraints not found",
        ) from exc
    except GoalsStateError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="GOALS_STATE_INVALID",
            message="Goals and constraints state is invalid",
        ) from exc

    return _build_goals_response(result)


@router.put(
    "/goals-and-constraints",
    response_model=GoalsAndConstraintsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_goals_and_constraints(
    body: GoalsAndConstraintsUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> GoalsAndConstraintsResponse:
    repository = SqlAlchemyGoalsRepository(session)
    service = GoalsService(repository)

    data = GoalsUpdateData(
        goal_type=body.goal_type,
        target_date=body.target_date,
        target_weight_kg=body.target_weight_kg,
        equipment=list(body.equipment),
        preferred_exercises=list(body.preferred_exercises),
        disliked_exercises=list(body.disliked_exercises),
        pain_or_injuries=[item.model_dump() for item in body.pain_or_injuries],
        allergies=list(body.allergies),
        dietary_preferences=list(body.dietary_preferences),
    )

    try:
        result = await service.update_goals_and_constraints(
            user_id=user.id,
            data=data,
            expected_version=body.expected_version,
        )
    except GoalsVersionRequiredError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="GOALS_VERSION_REQUIRED",
            message="expected_version is required",
        ) from exc
    except GoalsExerciseUnavailableError as exc:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="GOALS_EXERCISE_UNAVAILABLE",
            message="One or more preferred or disliked exercises are unavailable",
            details={"exercise_ids": sorted(str(item) for item in exc.exercise_ids)},
        ) from exc
    except GoalsVersionConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="GOALS_VERSION_CONFLICT",
            message="Goals and constraints have been modified",
            details={
                "expected_version": exc.expected_version,
                "current_version": exc.current_version,
            },
        ) from exc
    except GoalsStateError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="GOALS_STATE_INVALID",
            message="Goals and constraints state is invalid",
        ) from exc

    return _build_goals_response(result)
