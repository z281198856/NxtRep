from uuid import UUID

from fastapi import APIRouter

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.routes.media import ImageStorage
from nxtrep_backend.providers.storage import StorageProviderError
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
from nxtrep_backend.schemas.exercise import ExerciseMediaResponse

router = APIRouter()


@router.get("/{media_id}", response_model=ExerciseMediaResponse)
async def get_exercise_media(
    media_id: UUID,
    user: CurrentUser,
    session: DbSession,
    storage: ImageStorage,
) -> ExerciseMediaResponse:
    item = await SqlAlchemyExercisesRepository(session).get_media_for_user(
        user_id=user.id,
        media_id=media_id,
    )
    if item is None:
        raise ApiError(
            status_code=404,
            code="EXERCISE_MEDIA_NOT_FOUND",
            message="Exercise media not found",
        )
    try:
        signed = storage.presign_download(item.storage_key)
    except StorageProviderError as exc:
        raise ApiError(
            status_code=503,
            code="MEDIA_STORAGE_UNAVAILABLE",
            message="Exercise media is temporarily unavailable",
        ) from exc
    return ExerciseMediaResponse(
        id=item.id,
        exercise_id=item.exercise_id,
        media_type=item.media_type,
        view_angle=item.view_angle,
        alt_text=item.alt_text,
        sort_order=item.sort_order,
        download_url=signed.url,
        expires_at=signed.expires_at,
    )
