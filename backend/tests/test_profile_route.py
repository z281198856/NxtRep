from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import profile as profile_route
from nxtrep_backend.db.models import Profile, User
from nxtrep_backend.main import app
from nxtrep_backend.services.profile import (
    ProfileNotFoundError,
    ProfileVersionConflictError,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_session, None)


def build_update_profile_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncMock:
    update_profile = AsyncMock()
    service = MagicMock()
    service.update_profile = update_profile
    monkeypatch.setattr(
        profile_route,
        "ProfileService",
        MagicMock(return_value=service),
    )
    return update_profile


def test_get_profile_returns_current_user_profile(
    client: TestClient,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
        profile=Profile(
            display_name="思琪",
            sex="female",
            birth_date=date(2000, 1, 1),
            height_cm=Decimal("165.50"),
            experience_level="beginner",
            weekly_training_days=3,
            session_duration_minutes=60,
            timezone="Asia/Shanghai",
            version=1,
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: user

    response = client.get("/api/v1/profile")

    assert response.status_code == 200
    assert response.json() == {
        "display_name": "思琪",
        "sex": "female",
        "birth_date": "2000-01-01",
        "height_cm": "165.50",
        "experience_level": "beginner",
        "weekly_training_days": 3,
        "session_duration_minutes": 60,
        "timezone": "Asia/Shanghai",
        "version": 1,
    }


def test_get_profile_returns_404_when_profile_is_missing(
    client: TestClient,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
        profile=None,
    )
    app.dependency_overrides[get_current_user] = lambda: user

    response = client.get("/api/v1/profile")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "PROFILE_NOT_FOUND",
            "message": "Profile not found",
        }
    }


def test_get_profile_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/profile")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_update_profile_returns_updated_profile(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    update_profile = build_update_profile_mock(monkeypatch)
    updated_profile = Profile(
        user_id=user.id,
        display_name="思琪",
        sex="unspecified",
        birth_date=None,
        height_cm=None,
        experience_level=None,
        weekly_training_days=3,
        session_duration_minutes=None,
        timezone="Asia/Shanghai",
        version=2,
    )
    update_profile.return_value = updated_profile

    response = client.patch(
        "/api/v1/profile",
        json={
            "display_name": "  思琪  ",
            "weekly_training_days": 3,
            "expected_version": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "思琪"
    assert response.json()["weekly_training_days"] == 3
    assert response.json()["version"] == 2
    update_profile.assert_awaited_once_with(
        user_id=user.id,
        changes={
            "display_name": "思琪",
            "weekly_training_days": 3,
        },
        expected_version=1,
    )


def test_update_profile_returns_version_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    update_profile = build_update_profile_mock(monkeypatch)
    update_profile.side_effect = ProfileVersionConflictError(
        expected_version=1,
        current_version=2,
    )

    response = client.patch(
        "/api/v1/profile",
        json={
            "display_name": "思琪",
            "expected_version": 1,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "PROFILE_VERSION_CONFLICT",
            "message": "Profile has been modified",
            "details": {
                "expected_version": 1,
                "current_version": 2,
            },
        }
    }


def test_update_profile_returns_404_when_profile_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    update_profile = build_update_profile_mock(monkeypatch)
    update_profile.side_effect = ProfileNotFoundError

    response = client.patch(
        "/api/v1/profile",
        json={
            "display_name": "思琪",
            "expected_version": 1,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"


def test_update_profile_validates_request_before_calling_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    update_profile = build_update_profile_mock(monkeypatch)

    response = client.patch(
        "/api/v1/profile",
        json={"expected_version": 1},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    update_profile.assert_not_awaited()
