from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import RefreshSession, User
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository


@pytest.mark.asyncio
async def test_add_user_flushes_session() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    repository = SqlAlchemyUserRepository(session)
    user = User(username="zengsiqi")

    await repository.add(user)

    session.add.assert_called_once_with(user)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_username_is_case_insensitive() -> None:
    expected_user = User(username="ZengSiqi")
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=expected_user)

    repository = SqlAlchemyUserRepository(session)

    result = await repository.get_by_username("  ZENGSIQI  ")

    assert result is expected_user
    session.scalar.assert_awaited_once()

    statement = session.scalar.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "lower(users.username) = 'zengsiqi'" in compiled_statement
    assert "users.deleted_at IS NULL" in compiled_statement


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_user_does_not_exist() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)

    repository = SqlAlchemyUserRepository(session)

    result = await repository.get_by_id(uuid4())

    assert result is None
    session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_refresh_session_flushes_session() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()

    repository = SqlAlchemyUserRepository(session)
    refresh_session = RefreshSession(
        user_id=uuid4(),
        token_hash="hashed-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )

    await repository.add_refresh_session(refresh_session)

    session.add.assert_called_once_with(refresh_session)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_active_refresh_session_filters_invalid_sessions() -> None:
    expected_session = RefreshSession(
        user_id=uuid4(),
        token_hash="hashed-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=expected_session)

    repository = SqlAlchemyUserRepository(session)

    result = await repository.get_active_refresh_session_by_token_hash(
        "hashed-refresh-token",
        for_update=True,
    )

    assert result is expected_session

    statement = session.scalar.await_args.args[0]
    compiled_statement = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "refresh_sessions.token_hash = 'hashed-refresh-token'" in compiled_statement
    assert "refresh_sessions.revoked_at IS NULL" in compiled_statement
    assert "refresh_sessions.expires_at > now()" in compiled_statement
    assert "FOR UPDATE" in compiled_statement
