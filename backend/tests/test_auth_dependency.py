from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api import deps
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.config import Settings
from nxtrep_backend.core.tokens import create_access_token
from nxtrep_backend.db.models import User, UserStatus
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository


def make_settings(*, jwt_secret: str | None = "test-jwt-secret-" * 4) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr(jwt_secret) if jwt_secret is not None else None,
    )


def bearer_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token,
    )


def install_repository_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user: User | None,
) -> AsyncMock:
    get_by_id = AsyncMock(return_value=user)
    repository = MagicMock(spec=SqlAlchemyUserRepository)
    repository.get_by_id = get_by_id
    monkeypatch.setattr(
        deps,
        "SqlAlchemyUserRepository",
        MagicMock(return_value=repository),
    )
    return get_by_id


@pytest.mark.asyncio
async def test_current_user_accepts_valid_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = User(
        id=uuid4(),
        username="zengsiqi",
        status=UserStatus.ACTIVE.value,
        password_setup_required=False,
    )
    get_by_id = install_repository_mock(monkeypatch, user=user)
    session = MagicMock(spec=AsyncSession)
    token = create_access_token(user.id, settings)

    result = await deps.get_current_user(
        bearer_credentials(token),
        session,
        settings,
    )

    assert result is user
    get_by_id.assert_awaited_once_with(user.id)


@pytest.mark.asyncio
async def test_current_user_id_returns_authenticated_user_id() -> None:
    user = User(
        id=uuid4(),
        username="zengsiqi",
    )

    result = await deps.get_current_user_id(user)

    assert result == user.id


@pytest.mark.asyncio
async def test_current_user_rejects_missing_access_token() -> None:
    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            None,
            MagicMock(spec=AsyncSession),
            make_settings(),
        )

    assert error.value.status_code == 401
    assert error.value.code == "AUTHENTICATION_REQUIRED"
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_current_user_rejects_invalid_access_token() -> None:
    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            bearer_credentials("invalid-token"),
            MagicMock(spec=AsyncSession),
            make_settings(),
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"


@pytest.mark.asyncio
async def test_current_user_reports_missing_auth_configuration() -> None:
    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            bearer_credentials("access-token"),
            MagicMock(spec=AsyncSession),
            make_settings(jwt_secret=None),
        )

    assert error.value.status_code == 503
    assert error.value.code == "AUTH_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_current_user_rejects_token_for_unknown_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user_id = uuid4()
    install_repository_mock(monkeypatch, user=None)
    token = create_access_token(user_id, settings)

    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            bearer_credentials(token),
            MagicMock(spec=AsyncSession),
            settings,
        )

    assert error.value.status_code == 401
    assert error.value.code == "INVALID_ACCESS_TOKEN"


@pytest.mark.parametrize(
    ("status_value", "password_setup_required", "expected_status", "expected_code"),
    [
        (UserStatus.DISABLED.value, False, 403, "ACCOUNT_DISABLED"),
        (UserStatus.ACTIVE.value, True, 409, "PASSWORD_SETUP_REQUIRED"),
    ],
)
@pytest.mark.asyncio
async def test_current_user_checks_account_state(
    monkeypatch: pytest.MonkeyPatch,
    status_value: str,
    password_setup_required: bool,
    expected_status: int,
    expected_code: str,
) -> None:
    settings = make_settings()
    user = User(
        id=uuid4(),
        username="zengsiqi",
        status=status_value,
        password_setup_required=password_setup_required,
    )
    install_repository_mock(monkeypatch, user=user)
    token = create_access_token(user.id, settings)

    with pytest.raises(ApiError) as error:
        await deps.get_current_user(
            bearer_credentials(token),
            MagicMock(spec=AsyncSession),
            settings,
        )

    assert error.value.status_code == expected_status
    assert error.value.code == expected_code
