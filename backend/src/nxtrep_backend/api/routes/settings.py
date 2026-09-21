from fastapi import APIRouter, status

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.repositories.settings import SqlAlchemySettingsRepository
from nxtrep_backend.schemas.settings import SettingsResponse, SettingsUpdateRequest
from nxtrep_backend.services.settings import (
    SettingsService,
    SettingsVersionConflictError,
)

router = APIRouter()


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: CurrentUser,
    session: DbSession,
) -> SettingsResponse:
    item = await SettingsService(SqlAlchemySettingsRepository(session)).get(user_id=user.id)
    return SettingsResponse.model_validate(item)


@router.patch("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> SettingsResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    try:
        item = await SettingsService(SqlAlchemySettingsRepository(session)).update(
            user_id=user.id,
            changes=changes,
            expected_version=body.expected_version,
        )
    except SettingsVersionConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="SETTINGS_VERSION_CONFLICT",
            message="Settings have been modified",
            details={
                "expected_version": exc.expected_version,
                "current_version": exc.current_version,
            },
        ) from exc
    return SettingsResponse.model_validate(item)
