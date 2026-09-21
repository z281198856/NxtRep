from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from nxtrep_backend.core.config import Settings
from nxtrep_backend.core.security import hash_password, verify_password
from nxtrep_backend.core.tokens import decode_access_token, hash_opaque_token
from nxtrep_backend.db.models import Credential, RefreshSession, User, UserStatus
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.services.account import (
    AccountDisabledError,
    AccountLockedError,
    AccountService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    InvalidSetupTokenError,
    PasswordReuseError,
    PasswordSetupRequiredError,
    RefreshSessionNotFoundError,
    UsernameAlreadyExistsError,
)


@pytest.mark.asyncio
async def test_logout_revokes_matching_refresh_session_idempotently() -> None:
    token = "l" * 64
    refresh_session = RefreshSession(
        user_id=uuid4(),
        token_hash=hash_opaque_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_token_hash = AsyncMock(
        return_value=refresh_session
    )

    await AccountService(repository, make_settings()).logout(
        refresh_token=token
    )

    assert refresh_session.revoked_at is not None
    assert refresh_session.last_used_at is not None


@pytest.mark.asyncio
async def test_change_password_revokes_old_sessions_and_issues_new_pair() -> None:
    user = make_login_ready_user(password="current-password")
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)
    repository.revoke_active_refresh_sessions = AsyncMock()
    repository.add_refresh_session = AsyncMock()
    settings = make_settings()

    result = await AccountService(repository, settings).change_password(
        user_id=user.id,
        current_password="current-password",
        new_password="different-password",
        device_name="Windows",
    )

    assert verify_password("different-password", user.credential.password_hash)
    repository.revoke_active_refresh_sessions.assert_awaited_once()
    repository.add_refresh_session.assert_awaited_once()
    assert decode_access_token(result.access_token, settings) == user.id


@pytest.mark.asyncio
async def test_change_password_rejects_password_reuse() -> None:
    user = make_login_ready_user(password="current-password")
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = AsyncMock(return_value=user)

    with pytest.raises(PasswordReuseError):
        await AccountService(repository, make_settings()).change_password(
            user_id=user.id,
            current_password="current-password",
            new_password="current-password",
        )


@pytest.mark.asyncio
async def test_revoke_session_rejects_unknown_or_foreign_session() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_id = AsyncMock(return_value=None)

    with pytest.raises(RefreshSessionNotFoundError):
        await AccountService(repository, make_settings()).revoke_session(
            user_id=uuid4(),
            session_id=uuid4(),
        )


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr("unit-test-jwt-secret-" * 4),
        access_token_expire_minutes=15,
        refresh_token_expire_days=30,
        password_setup_token_expire_minutes=30,
    )


def make_user_waiting_for_password(
    setup_token: str,
    *,
    expires_at: datetime | None = None,
    password_setup_required: bool = True,
) -> User:
    return User(
        id=uuid4(),
        username="zengsiqi",
        password_setup_required=password_setup_required,
        credential=Credential(
            password_hash=None,
            setup_token_hash=hash_opaque_token(setup_token),
            setup_token_expires_at=(
                expires_at if expires_at is not None else datetime.now(UTC) + timedelta(minutes=30)
            ),
        ),
    )


def make_login_ready_user(
    *,
    password: str = "correct-password",
    status: str = UserStatus.ACTIVE.value,
    password_setup_required: bool = False,
    locked_until: datetime | None = None,
) -> User:
    return User(
        id=uuid4(),
        username="zengsiqi",
        status=status,
        password_setup_required=password_setup_required,
        credential=Credential(
            password_hash=hash_password(password),
            failed_login_attempts=0,
            locked_until=locked_until,
        ),
    )


@pytest.mark.asyncio
async def test_precreate_user_builds_account() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=None)
    repository.add = AsyncMock()

    service = AccountService(repository, make_settings())

    earliest_expiration = datetime.now(UTC) + timedelta(minutes=29)

    result = await service.precreate_user(
        username="  zengsiqi  ",
        display_name="  Zeng  ",
        is_admin=False,
    )

    assert result.user.username == "zengsiqi"
    assert result.user.is_admin is False
    assert result.user.password_setup_required is True

    assert result.user.credential is not None
    assert result.user.credential.password_hash is None
    assert result.user.credential.setup_token_hash == hash_opaque_token(result.setup_token)
    assert result.user.credential.setup_token_expires_at == result.setup_token_expires_at

    assert result.user.profile is not None
    assert result.user.profile.display_name == "Zeng"
    assert result.setup_token_expires_at > earliest_expiration

    repository.add.assert_awaited_once_with(result.user)


@pytest.mark.asyncio
async def test_precreate_user_rejects_existing_username() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=User(username="zengsiqi"))
    repository.add = AsyncMock()

    service = AccountService(repository, make_settings())

    with pytest.raises(UsernameAlreadyExistsError):
        await service.precreate_user(username="ZENGSIQI")

    repository.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_precreate_user_handles_database_unique_conflict() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=None)
    repository.add = AsyncMock(
        side_effect=IntegrityError(
            "INSERT INTO users",
            {},
            Exception("duplicate username"),
        )
    )

    service = AccountService(repository, make_settings())

    with pytest.raises(UsernameAlreadyExistsError):
        await service.precreate_user(username="zengsiqi")


@pytest.mark.asyncio
async def test_setup_password_issues_tokens_and_clears_setup_token() -> None:
    setup_token = "s" * 64
    user = make_user_waiting_for_password(setup_token)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    settings = make_settings()
    service = AccountService(repository, settings)

    earliest_refresh_expiration = datetime.now(UTC) + timedelta(days=29)

    result = await service.setup_password(
        username="zengsiqi",
        setup_token=setup_token,
        new_password="new-password-123",
    )

    repository.get_by_username.assert_awaited_once_with(
        "zengsiqi",
        for_update=True,
    )
    assert result.user is user
    assert result.expires_in == 900
    assert decode_access_token(result.access_token, settings) == user.id

    assert user.password_setup_required is False
    assert user.credential is not None
    assert user.credential.password_hash is not None
    assert verify_password(
        "new-password-123",
        user.credential.password_hash,
    )
    assert user.credential.setup_token_hash is None
    assert user.credential.setup_token_expires_at is None
    assert user.credential.password_changed_at is not None
    assert user.credential.failed_login_attempts == 0
    assert user.credential.locked_until is None

    repository.add_refresh_session.assert_awaited_once()
    refresh_session = repository.add_refresh_session.await_args.args[0]
    assert refresh_session.user_id == user.id
    assert refresh_session.token_hash == hash_opaque_token(result.refresh_token)
    assert refresh_session.expires_at > earliest_refresh_expiration


@pytest.mark.asyncio
async def test_setup_password_rejects_wrong_setup_token() -> None:
    user = make_user_waiting_for_password("correct-token" * 6)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidSetupTokenError):
        await service.setup_password(
            username="zengsiqi",
            setup_token="wrong-token" * 6,
            new_password="new-password-123",
        )

    repository.add_refresh_session.assert_not_awaited()
    assert user.password_setup_required is True
    assert user.credential is not None
    assert user.credential.password_hash is None


@pytest.mark.asyncio
async def test_setup_password_rejects_expired_setup_token() -> None:
    setup_token = "expired-token" * 6
    user = make_user_waiting_for_password(
        setup_token,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidSetupTokenError):
        await service.setup_password(
            username="zengsiqi",
            setup_token=setup_token,
            new_password="new-password-123",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_password_rejects_reused_setup_token() -> None:
    setup_token = "used-token" * 7
    user = make_user_waiting_for_password(
        setup_token,
        password_setup_required=False,
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidSetupTokenError):
        await service.setup_password(
            username="zengsiqi",
            setup_token=setup_token,
            new_password="new-password-123",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_password_rejects_unknown_user() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=None)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidSetupTokenError):
        await service.setup_password(
            username="missing-user",
            setup_token="unknown-token" * 6,
            new_password="new-password-123",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_issues_tokens_and_records_device() -> None:
    user = make_login_ready_user()
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    settings = make_settings()
    service = AccountService(repository, settings)

    result = await service.login(
        username="zengsiqi",
        password="correct-password",
        device_name="iPhone",
    )

    repository.get_by_username.assert_awaited_once_with(
        "zengsiqi",
        for_update=True,
    )
    assert result.user is user
    assert result.expires_in == 900
    assert decode_access_token(result.access_token, settings) == user.id
    assert user.last_login_at is not None

    repository.add_refresh_session.assert_awaited_once()
    refresh_session = repository.add_refresh_session.await_args.args[0]
    assert refresh_session.user_id == user.id
    assert refresh_session.device_name == "iPhone"
    assert refresh_session.token_hash == hash_opaque_token(result.refresh_token)


@pytest.mark.asyncio
async def test_login_rejects_wrong_password() -> None:
    user = make_login_ready_user()
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidCredentialsError):
        await service.login(
            username="zengsiqi",
            password="wrong-password",
        )

    assert user.credential.failed_login_attempts == 1
    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_locks_account_on_fifth_failed_attempt() -> None:
    user = make_login_ready_user()
    user.credential.failed_login_attempts = 4
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()

    with pytest.raises(AccountLockedError):
        await AccountService(repository, make_settings()).login(
            username="zengsiqi",
            password="wrong-password",
        )

    assert user.credential.failed_login_attempts == 5
    assert user.credential.locked_until is not None


@pytest.mark.asyncio
async def test_login_rejects_disabled_account() -> None:
    user = make_login_ready_user(status=UserStatus.DISABLED.value)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(AccountDisabledError):
        await service.login(
            username="zengsiqi",
            password="correct-password",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_requires_initial_password_setup() -> None:
    user = make_login_ready_user(password_setup_required=True)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(PasswordSetupRequiredError):
        await service.login(
            username="zengsiqi",
            password="correct-password",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_login_rejects_locked_account() -> None:
    user = make_login_ready_user(
        locked_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_username = AsyncMock(return_value=user)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(AccountLockedError):
        await service.login(
            username="zengsiqi",
            password="correct-password",
        )

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_tokens_rotates_session() -> None:
    old_refresh_token = "o" * 64
    user = make_login_ready_user()
    old_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_opaque_token(old_refresh_token),
        device_name="iPhone",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        user=user,
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_token_hash = AsyncMock(return_value=old_session)
    repository.add_refresh_session = AsyncMock()
    settings = make_settings()
    service = AccountService(repository, settings)

    result = await service.refresh_tokens(
        refresh_token=old_refresh_token,
    )

    repository.get_active_refresh_session_by_token_hash.assert_awaited_once_with(
        hash_opaque_token(old_refresh_token),
        for_update=True,
    )
    assert result.user is user
    assert result.refresh_token != old_refresh_token
    assert decode_access_token(result.access_token, settings) == user.id
    assert old_session.last_used_at is not None
    assert old_session.revoked_at is not None

    repository.add_refresh_session.assert_awaited_once()
    new_session = repository.add_refresh_session.await_args.args[0]
    assert new_session.user_id == user.id
    assert new_session.device_name == "iPhone"
    assert new_session.token_hash == hash_opaque_token(result.refresh_token)
    assert new_session.revoked_at is None


@pytest.mark.asyncio
async def test_refresh_tokens_rejects_invalid_token() -> None:
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_token_hash = AsyncMock(return_value=None)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh_tokens(refresh_token="i" * 64)

    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_tokens_rejects_disabled_account() -> None:
    user = make_login_ready_user(status=UserStatus.DISABLED.value)
    old_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_opaque_token("o" * 64),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        user=user,
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_token_hash = AsyncMock(return_value=old_session)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(AccountDisabledError):
        await service.refresh_tokens(refresh_token="o" * 64)

    assert old_session.revoked_at is None
    repository.add_refresh_session.assert_not_awaited()


@pytest.mark.parametrize(
    ("deleted_at", "password_setup_required"),
    [
        (datetime.now(UTC), False),
        (None, True),
    ],
)
@pytest.mark.asyncio
async def test_refresh_tokens_rejects_unusable_account(
    deleted_at: datetime | None,
    password_setup_required: bool,
) -> None:
    user = make_login_ready_user(
        password_setup_required=password_setup_required,
    )
    user.deleted_at = deleted_at
    old_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_opaque_token("o" * 64),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        user=user,
    )
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_active_refresh_session_by_token_hash = AsyncMock(return_value=old_session)
    repository.add_refresh_session = AsyncMock()
    service = AccountService(repository, make_settings())

    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh_tokens(refresh_token="o" * 64)

    assert old_session.revoked_at is None
    repository.add_refresh_session.assert_not_awaited()
