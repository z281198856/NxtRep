from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_db_session
from nxtrep_backend.api.routes import auth as auth_route
from nxtrep_backend.core.tokens import AuthConfigurationError
from nxtrep_backend.db.models import User
from nxtrep_backend.main import app
from nxtrep_backend.services.account import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    IssuedTokenPair,
    PasswordSetupRequiredError,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def build_login_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    login = AsyncMock()
    service = MagicMock()
    service.login = login
    monkeypatch.setattr(
        auth_route,
        "AccountService",
        MagicMock(return_value=service),
    )
    return login


def valid_login_body() -> dict[str, str]:
    return {
        "username": " zengsiqi ",
        "password": "correct-password",
        "device_name": " iPhone ",
    }


def test_login_returns_token_pair(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = build_login_mock(monkeypatch)
    user = User(
        id=uuid4(),
        username="zengsiqi",
        password_setup_required=False,
    )
    login.return_value = IssuedTokenPair(
        access_token="access-token",
        refresh_token="r" * 32,
        expires_in=900,
        user=user,
    )

    response = client.post(
        "/api/v1/auth/login",
        json=valid_login_body(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "access-token",
        "refresh_token": "r" * 32,
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "id": str(user.id),
            "username": "zengsiqi",
            "password_setup_required": False,
        },
    }
    login.assert_awaited_once_with(
        username="zengsiqi",
        password="correct-password",
        device_name="iPhone",
    )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_message"),
    [
        (
            InvalidCredentialsError(),
            401,
            "INVALID_CREDENTIALS",
            "Invalid username or password",
        ),
        (
            AccountDisabledError(),
            403,
            "ACCOUNT_DISABLED",
            "Account is disabled",
        ),
        (
            PasswordSetupRequiredError(),
            409,
            "PASSWORD_SETUP_REQUIRED",
            "Password setup is required",
        ),
        (
            AccountLockedError(),
            423,
            "ACCOUNT_LOCKED",
            "Account is temporarily locked",
        ),
        (
            AuthConfigurationError(),
            503,
            "AUTH_NOT_CONFIGURED",
            "Authentication service is not configured",
        ),
    ],
)
def test_login_maps_service_errors_to_http_responses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    login = build_login_mock(monkeypatch)
    login.side_effect = error

    response = client.post(
        "/api/v1/auth/login",
        json=valid_login_body(),
    )

    assert response.status_code == expected_status
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": expected_message,
        }
    }

    if expected_status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


def test_login_validates_request_before_calling_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = build_login_mock(monkeypatch)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "zengsiqi",
            "password": "",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["details"][0]["loc"] == ["body", "password"]
    login.assert_not_awaited()
