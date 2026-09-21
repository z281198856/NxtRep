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
    InvalidRefreshTokenError,
    IssuedTokenPair,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def build_refresh_tokens_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    refresh_tokens = AsyncMock()
    service = MagicMock()
    service.refresh_tokens = refresh_tokens
    monkeypatch.setattr(
        auth_route,
        "AccountService",
        MagicMock(return_value=service),
    )
    return refresh_tokens


def test_refresh_returns_rotated_token_pair(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_tokens = build_refresh_tokens_mock(monkeypatch)
    user = User(
        id=uuid4(),
        username="zengsiqi",
        password_setup_required=False,
    )
    refresh_tokens.return_value = IssuedTokenPair(
        access_token="new-access-token",
        refresh_token="n" * 64,
        expires_in=900,
        refresh_expires_in=2_592_000,
        user=user,
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "o" * 64},
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "new-access-token",
        "refresh_token": "n" * 64,
        "token_type": "bearer",
        "expires_in": 900,
        "refresh_expires_in": 2_592_000,
        "user": {
            "id": str(user.id),
            "username": "zengsiqi",
            "password_setup_required": False,
        },
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    refresh_tokens.assert_awaited_once_with(
        refresh_token="o" * 64,
    )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_message"),
    [
        (
            InvalidRefreshTokenError(),
            401,
            "INVALID_REFRESH_TOKEN",
            "Invalid or expired refresh token",
        ),
        (
            AccountDisabledError(),
            403,
            "ACCOUNT_DISABLED",
            "Account is disabled",
        ),
        (
            AuthConfigurationError(),
            503,
            "AUTH_NOT_CONFIGURED",
            "Authentication service is not configured",
        ),
    ],
)
def test_refresh_maps_service_errors_to_http_responses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    refresh_tokens = build_refresh_tokens_mock(monkeypatch)
    refresh_tokens.side_effect = error

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "o" * 64},
    )

    assert response.status_code == expected_status
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": expected_message,
        }
    }


def test_refresh_validates_request_before_calling_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_tokens = build_refresh_tokens_mock(monkeypatch)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "too-short"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    refresh_tokens.assert_not_awaited()
