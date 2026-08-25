from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Profile


class SqlAlchemyProfileRepository:
    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def get_by_user_id(
        self,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> Profile | None:
        statement = select(Profile).where(
            Profile.user_id == user_id,
        )

        if for_update:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)
