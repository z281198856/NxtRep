from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nxtrep_backend.db.models import RefreshSession, User


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()

    async def get_by_username(
        self,
        username: str,
        *,
        for_update: bool = False,
    ) -> User | None:
        normalized_username = username.strip().lower()

        statement = (
            select(User)
            .options(
                selectinload(User.credential),
                selectinload(User.profile),
            )
            .where(
                func.lower(User.username) == normalized_username,
                User.deleted_at.is_(None),
            )
        )

        if for_update:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def get_by_id(
        self,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.credential),
                selectinload(User.profile),
            )
            .where(
                User.id == user_id,
                User.deleted_at.is_(None),
            )
        )

        if for_update:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def add_refresh_session(
        self,
        refresh_session: RefreshSession,
    ) -> None:
        self._session.add(refresh_session)
        await self._session.flush()

    async def get_active_refresh_session_by_token_hash(
        self,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None:
        statement = (
            select(RefreshSession)
            .options(selectinload(RefreshSession.user))
            .where(
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > func.now(),
            )
        )

        if for_update:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def list_active_refresh_sessions(
        self,
        user_id: UUID,
    ) -> list[RefreshSession]:
        statement = (
            select(RefreshSession)
            .where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > func.now(),
            )
            .order_by(RefreshSession.created_at.desc(), RefreshSession.id.desc())
        )
        return list(await self._session.scalars(statement))

    async def get_active_refresh_session_by_id(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        for_update: bool = False,
    ) -> RefreshSession | None:
        statement = select(RefreshSession).where(
            RefreshSession.id == session_id,
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > func.now(),
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def revoke_active_refresh_sessions(
        self,
        *,
        user_id: UUID,
        revoked_at: datetime,
    ) -> None:
        await self._session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
