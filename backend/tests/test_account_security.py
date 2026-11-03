from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from test_account_service import make_login_ready_user, make_settings
from test_auth_dependency import bearer_credentials

from nxtrep_backend.api import deps
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.tokens import create_access_token, decode_access_token_claims
from nxtrep_backend.db.models import RefreshSession
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.services.account import AccountLockedError, AccountService


def test_token_binds_login_session_without_exposing_refresh_secret():
    settings = make_settings()
    user_id, session_id = uuid4(), uuid4()
    claims = decode_access_token_claims(
        create_access_token(user_id, settings, session_id=session_id), settings
    )
    assert claims.user_id == user_id and claims.session_id == session_id


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [True, False])
async def test_bound_access_checks_live_session_and_owner(monkeypatch, active):
    settings = make_settings()
    user = make_login_ready_user()
    session_id = uuid4()
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    repository.get_active_refresh_session_by_id = AsyncMock(
        return_value=RefreshSession(id=session_id, user_id=user.id) if active else None
    )
    monkeypatch.setattr(deps, "SqlAlchemyUserRepository", lambda _: repository)
    token = create_access_token(user.id, settings, session_id=session_id)
    if active:
        current = await deps.get_current_user(
            bearer_credentials(token), MagicMock(spec=AsyncSession), settings
        )
        assert current is user
        assert await deps.get_current_session_id(current) == session_id
    else:
        with pytest.raises(ApiError) as error:
            await deps.get_current_user(
                bearer_credentials(token), MagicMock(spec=AsyncSession), settings
            )
        assert error.value.code == "INVALID_ACCESS_TOKEN"
    repository.get_active_refresh_session_by_id.assert_awaited_once_with(
        user_id=user.id, session_id=session_id
    )


@pytest.mark.asyncio
async def test_unbound_legacy_access_requires_refresh_before_business_access(monkeypatch):
    settings = make_settings()
    user = make_login_ready_user()
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    monkeypatch.setattr(deps, "SqlAlchemyUserRepository", lambda _: repository)
    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            bearer_credentials(create_access_token(user.id, settings)),
            MagicMock(spec=AsyncSession),
            settings,
        )
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_bulk_revoke_excludes_authenticated_session():
    user = make_login_ready_user()
    session_id = uuid4()
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    repository.get_active_refresh_session_by_id = AsyncMock(
        return_value=RefreshSession(id=session_id)
    )
    repository.revoke_active_refresh_sessions = AsyncMock()
    await AccountService(repository, make_settings()).revoke_other_sessions(
        user_id=user.id, current_session_id=session_id
    )
    assert (
        repository.revoke_active_refresh_sessions.await_args.kwargs["except_session_id"]
        == session_id
    )
    assert repository.revoke_active_refresh_sessions.await_args.kwargs["user_id"] == user.id


@pytest.mark.asyncio
async def test_password_change_locks_after_repeated_current_password_errors():
    user = make_login_ready_user()
    user.credential.failed_login_attempts = 4
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    with pytest.raises(AccountLockedError):
        await AccountService(repository, make_settings()).change_password(
            user_id=user.id, current_password="wrong", new_password="another-valid-password"
        )
    assert user.credential.failed_login_attempts == 5
    assert user.credential.locked_until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_password_change_respects_existing_lock():
    user = make_login_ready_user()
    user.credential.locked_until = datetime.now(UTC) + timedelta(minutes=15)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    with pytest.raises(AccountLockedError):
        await AccountService(repository, make_settings()).change_password(
            user_id=user.id,
            current_password="correct-password",
            new_password="another-valid-password",
        )
