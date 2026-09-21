from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import ImageAsset


class SqlAlchemyImageAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, asset: ImageAsset) -> ImageAsset:
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def get_owned(
        self,
        *,
        user_id: UUID,
        asset_id: UUID,
        lock: bool = False,
        include_deleted: bool = False,
    ) -> ImageAsset | None:
        conditions = [
            ImageAsset.id == asset_id,
            ImageAsset.user_id == user_id,
        ]

        if not include_deleted:
            conditions.append(ImageAsset.deleted_at.is_(None))

        statement = select(ImageAsset).where(*conditions)

        if lock:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def save(self, asset: ImageAsset) -> ImageAsset:
        await self._session.flush()
        return asset

    async def list_expired_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[ImageAsset]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        statement = (
            select(ImageAsset)
            .where(
                ImageAsset.status == "pending_upload",
                ImageAsset.upload_expires_at <= now,
                ImageAsset.deleted_at.is_(None),
            )
            .order_by(
                ImageAsset.upload_expires_at,
                ImageAsset.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        result = await self._session.scalars(statement)
        return list(result.all())
