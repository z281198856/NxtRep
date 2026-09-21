from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import admin as admin_route
from nxtrep_backend.api.routes import auth as auth_route
from nxtrep_backend.db.models import Profile, RefreshSession, User
from nxtrep_backend.main import app
from nxtrep_backend.services.account import PrecreatedUser


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid4(),
        username="tester",
        status="active",
        is_admin=False,
        password_setup_required=False,
        profile=Profile(
            display_name="Tester",
            experience_level="beginner",
            weekly_training_days=3,
        ),
    )


@pytest.fixture
def client(current_user: User) -> Iterator[TestClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = lambda: current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_me_reports_identity_and_initialization(
    client: TestClient,
    current_user: User,
) -> None:
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["id"] == str(current_user.id)
    assert response.json()["profile_initialized"] is True


def test_logout_is_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    service.logout = AsyncMock()
    monkeypatch.setattr(auth_route, "AccountService", MagicMock(return_value=service))

    response = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "r" * 64},
    )

    assert response.status_code == 204
    service.logout.assert_awaited_once_with(refresh_token="r" * 64)


def test_session_list_returns_only_service_results(
    client: TestClient,
    current_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = RefreshSession(
        id=uuid4(),
        user_id=current_user.id,
        token_hash="hashed",
        device_name="Windows",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    service = MagicMock()
    service.list_sessions = AsyncMock(return_value=[item])
    monkeypatch.setattr(auth_route, "AccountService", MagicMock(return_value=service))

    response = client.get("/api/v1/auth/sessions")

    assert response.status_code == 200
    assert response.json()["sessions"][0]["device_name"] == "Windows"
    service.list_sessions.assert_awaited_once_with(user_id=current_user.id)


def test_non_admin_cannot_precreate_user(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_service = MagicMock()
    account_service.precreate_user = AsyncMock()
    monkeypatch.setattr(
        admin_route,
        "AccountService",
        MagicMock(return_value=account_service),
    )

    response = client.post(
        "/api/v1/admin/users",
        json={"username": "new-user"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"
    account_service.precreate_user.assert_not_awaited()


def test_admin_can_precreate_user(
    client: TestClient,
    current_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_user.is_admin = True
    created_user = User(
        id=uuid4(),
        username="new-user",
        is_admin=False,
        password_setup_required=True,
        profile=Profile(display_name="New User"),
    )
    account_service = MagicMock()
    account_service.precreate_user = AsyncMock(
        return_value=PrecreatedUser(
            user=created_user,
            setup_token="s" * 64,
            setup_token_expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    monkeypatch.setattr(
        admin_route,
        "AccountService",
        MagicMock(return_value=account_service),
    )

    response = client.post(
        "/api/v1/admin/users",
        json={"username": "new-user", "display_name": "New User"},
    )

    assert response.status_code == 201
    assert response.json()["username"] == "new-user"
    assert response.json()["setup_token"] == "s" * 64
