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
    InvalidSetupTokenError,
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


def build_account_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    setup_password = AsyncMock()
    service = MagicMock()
    service.setup_password = setup_password
    monkeypatch.setattr(
        auth_route,
        "AccountService",
        MagicMock(return_value=service),
    )
    return setup_password


def test_setup_password_returns_token_pair(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_password = build_account_service_mock(monkeypatch)
    user = User(
        id=uuid4(),
        username="zengsiqi",
        password_setup_required=False,
    )
    setup_password.return_value = IssuedTokenPair(
        access_token="access-token",
        refresh_token="r" * 32,
        expires_in=900,
        user=user,
    )

    response = client.post(
        "/api/v1/auth/password/setup",
        json={
            "username": " zengsiqi ",
            "setup_token": "s" * 32,
            "new_password": "new-password-123",
        },
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
    setup_password.assert_awaited_once_with(
        username="zengsiqi",
        setup_token="s" * 32,
        new_password="new-password-123",
    )


def test_setup_password_rejects_invalid_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_password = build_account_service_mock(monkeypatch)
    setup_password.side_effect = InvalidSetupTokenError

    response = client.post(
        "/api/v1/auth/password/setup",
        json={
            "username": "zengsiqi",
            "setup_token": "i" * 32,
            "new_password": "new-password-123",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INVALID_SETUP_TOKEN",
            "message": "Invalid or expired setup token",
        }
    }


def test_setup_password_returns_503_when_auth_is_not_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_password = build_account_service_mock(monkeypatch)
    setup_password.side_effect = AuthConfigurationError

    response = client.post(
        "/api/v1/auth/password/setup",
        json={
            "username": "zengsiqi",
            "setup_token": "s" * 32,
            "new_password": "new-password-123",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "AUTH_NOT_CONFIGURED",
            "message": "Authentication service is not configured",
        }
    }


def test_setup_password_validates_request_before_calling_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_password = build_account_service_mock(monkeypatch)

    response = client.post(
        "/api/v1/auth/password/setup",
        json={
            "username": "zengsiqi",
            "setup_token": "s" * 32,
            "new_password": "short",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    setup_password.assert_not_awaited()
