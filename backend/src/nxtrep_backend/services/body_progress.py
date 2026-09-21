from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nxtrep_backend.db.models import BodyProgressPhoto
from nxtrep_backend.repositories.body_progress import SqlAlchemyBodyProgressPhotoRepository
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository
from nxtrep_backend.schemas.body_progress import BodyProgressPhotoCreateRequest


class BodyProgressPhotoNotFoundError(RuntimeError):
    pass


class BodyProgressPhotoConflictError(RuntimeError):
    pass


class BodyProgressPhotoService:
    def __init__(
        self,
        repository: SqlAlchemyBodyProgressPhotoRepository,
        image_repository: SqlAlchemyImageAssetRepository,
    ) -> None:
        self.repository = repository
        self.image_repository = image_repository

    async def create(
        self,
        *,
        user_id: UUID,
        body: BodyProgressPhotoCreateRequest,
    ) -> BodyProgressPhoto:
        image = await self.image_repository.get_owned(
            user_id=user_id,
            asset_id=body.image_asset_id,
        )
        if image is None:
            raise BodyProgressPhotoNotFoundError("Image asset not found")
        if image.status != "ready":
            raise BodyProgressPhotoConflictError("Image asset is not ready")
        if image.purpose not in {"body_progress", "chat_attachment"}:
            raise BodyProgressPhotoConflictError("Image is not a body progress photo")
        existing = await self.repository.get_by_asset(
            user_id=user_id,
            image_asset_id=body.image_asset_id,
        )
        if existing is not None:
            return existing
        return await self.repository.add(
            BodyProgressPhoto(
                user_id=user_id,
                image_asset_id=body.image_asset_id,
                captured_at=body.captured_at,
                view=body.view,
                notes=body.notes,
                assessment=body.assessment,
            )
        )

    async def list(self, *, user_id: UUID, limit: int = 20) -> list[BodyProgressPhoto]:
        return await self.repository.list_active(user_id=user_id, limit=limit)

    async def save_assessment(
        self,
        *,
        user_id: UUID,
        photo_id: UUID,
        assessment: dict[str, Any],
    ) -> BodyProgressPhoto:
        item = await self.repository.get_owned(
            user_id=user_id,
            photo_id=photo_id,
            lock=True,
        )
        if item is None:
            raise BodyProgressPhotoNotFoundError("Body progress photo not found")
        item.assessment = assessment
        item.version += 1
        await self.repository.flush()
        return item

    async def delete(
        self,
        *,
        user_id: UUID,
        photo_id: UUID,
        expected_version: int,
    ) -> BodyProgressPhoto:
        item = await self.repository.get_owned(
            user_id=user_id,
            photo_id=photo_id,
            lock=True,
        )
        if item is None:
            raise BodyProgressPhotoNotFoundError("Body progress photo not found")
        if item.version != expected_version:
            raise BodyProgressPhotoConflictError("Body progress photo was modified")
        item.deleted_at = datetime.now(UTC)
        item.version += 1
        await self.repository.flush()
        return item
