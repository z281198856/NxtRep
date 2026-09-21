from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import BodyProgressPhoto


class SqlAlchemyBodyProgressPhotoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, item: BodyProgressPhoto) -> BodyProgressPhoto:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_owned(
        self,
        *,
        user_id: UUID,
        photo_id: UUID,
        lock: bool = False,
    ) -> BodyProgressPhoto | None:
        statement = select(BodyProgressPhoto).where(
            BodyProgressPhoto.id == photo_id,
            BodyProgressPhoto.user_id == user_id,
            BodyProgressPhoto.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_active(
        self,
        *,
        user_id: UUID,
        limit: int,
    ) -> list[BodyProgressPhoto]:
        return list(
            await self.session.scalars(
                select(BodyProgressPhoto)
                .where(
                    BodyProgressPhoto.user_id == user_id,
                    BodyProgressPhoto.deleted_at.is_(None),
                )
                .order_by(BodyProgressPhoto.captured_at.desc())
                .limit(limit)
            )
        )

    async def get_by_asset(
        self,
        *,
        user_id: UUID,
        image_asset_id: UUID,
    ) -> BodyProgressPhoto | None:
        return await self.session.scalar(
            select(BodyProgressPhoto).where(
                BodyProgressPhoto.user_id == user_id,
                BodyProgressPhoto.image_asset_id == image_asset_id,
                BodyProgressPhoto.deleted_at.is_(None),
            )
        )

    async def flush(self) -> None:
        await self.session.flush()
