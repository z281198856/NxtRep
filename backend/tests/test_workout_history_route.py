from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import workout as workout_route
from nxtrep_backend.db.models import User
from nxtrep_backend.main import app
from nxtrep_backend.schemas.workout import (
    WorkoutHistoryItem,
    WorkoutHistoryResponse,
)


@pytest.fixture
def client() -> Iterator[tuple[TestClient, MagicMock, User]]:
    session = MagicMock(spec=AsyncSession)
    user = User(
        id=uuid4(),
        username="history-user",
        password_setup_required=False,
    )

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as test_client:
        yield test_client, session, user

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_current_user, None)


def build_service_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock]:
    service = MagicMock()
    service.list_history = AsyncMock()
    service_factory = MagicMock(return_value=service)
    monkeypatch.setattr(workout_route, "_service", service_factory)
    return service, service_factory


def test_history_route_forwards_user_and_filters_to_service(
    client: tuple[TestClient, MagicMock, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session, user = client
    service, service_factory = build_service_mock(monkeypatch)
    workout_id = uuid4()
    service.list_history.return_value = WorkoutHistoryResponse(
        list=[
            WorkoutHistoryItem(
                id=workout_id,
                date=date(2026, 9, 2),
                status="completed",
                duration_seconds=3600,
                completed_sets=12,
                total_volume_kg=Decimal("4200.500"),
                pr_count=1,
            )
        ],
        total=1,
        page=2,
        page_size=5,
        has_more=False,
    )

    response = test_client.get(
        "/api/v1/workouts",
        params={
            "start_date": "2026-08-20",
            "end_date": "2026-09-03",
            "status": "completed",
            "page": 2,
            "page_size": 5,
        },
    )

    assert response.status_code == 200
    service_factory.assert_called_once_with(session)
    service.list_history.assert_awaited_once_with(
        user_id=user.id,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 3),
        status="completed",
        page=2,
        page_size=5,
    )
    assert response.json()["list"][0]["id"] == str(workout_id)
    assert response.json()["list"][0]["total_volume_kg"] == "4200.500"


def test_history_route_rejects_reversed_date_range(
    client: tuple[TestClient, MagicMock, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _, _ = client
    service, _ = build_service_mock(monkeypatch)

    response = test_client.get(
        "/api/v1/workouts",
        params={
            "start_date": "2026-09-03",
            "end_date": "2026-09-02",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"
    service.list_history.assert_not_awaited()


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
    ],
)
def test_history_route_rejects_invalid_pagination(
    client: tuple[TestClient, MagicMock, User],
    monkeypatch: pytest.MonkeyPatch,
    params: dict,
) -> None:
    test_client, _, _ = client
    service, _ = build_service_mock(monkeypatch)

    response = test_client.get(
        "/api/v1/workouts",
        params=params,
    )

    assert response.status_code == 422
    service.list_history.assert_not_awaited()
