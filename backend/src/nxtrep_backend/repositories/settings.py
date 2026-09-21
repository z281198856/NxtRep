from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Profile, UserSettings


class SqlAlchemySettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> UserSettings | None:
        statement = select(UserSettings).where(UserSettings.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def add(self, settings: UserSettings) -> UserSettings:
        self._session.add(settings)
        await self._session.flush()
        return settings

    async def get_profile_for_update(self, user_id: UUID) -> Profile | None:
        return await self._session.scalar(
            select(Profile).where(Profile.user_id == user_id).with_for_update()
        )
