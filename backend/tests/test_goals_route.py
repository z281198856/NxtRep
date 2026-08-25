from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import profile as profile_route
from nxtrep_backend.db.models import User, UserConstraint, UserGoal
from nxtrep_backend.main import app
from nxtrep_backend.services.goals import (
    GoalsNotFoundError,
    GoalsStateError,
    GoalsUpdateResult,
    GoalsVersionConflictError,
    GoalsVersionRequiredError,
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


def build_goals_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    update_goals = AsyncMock()
    service = MagicMock()
    service.update_goals_and_constraints = update_goals
    monkeypatch.setattr(
        profile_route,
        "GoalsService",
        MagicMock(return_value=service),
    )
    return update_goals


def build_get_goals_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    get_goals = AsyncMock()
    service = MagicMock()
    service.get_goals_and_constraints = get_goals
    monkeypatch.setattr(
        profile_route,
        "GoalsService",
        MagicMock(return_value=service),
    )
    return get_goals


def make_user() -> User:
    return User(
        id=uuid4(),
        username="Qiiii",
        password_setup_required=False,
    )


def make_result(*, user_id: UUID) -> GoalsUpdateResult:
    return GoalsUpdateResult(
        goal=UserGoal(
            id=uuid4(),
            user_id=user_id,
            goal_type="strength",
            target_date=None,
            target_weight_kg=None,
            status="active",
            version=2,
        ),
        constraints=UserConstraint(
            user_id=user_id,
            equipment=["barbell"],
            preferred_exercise_ids=[],
            disliked_exercise_ids=[],
            pain_or_injuries=[],
            allergies=[],
            dietary_preferences=[],
            version=2,
        ),
        warnings=[],
    )


def test_get_goals_returns_current_resource(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    get_goals = build_get_goals_service_mock(monkeypatch)
    get_goals.return_value = make_result(user_id=user.id)

    response = client.get("/api/v1/profile/goals-and-constraints")

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["goal"]["goal_type"] == "strength"
    assert response.json()["constraints"]["equipment"] == ["barbell"]
    get_goals.assert_awaited_once_with(user_id=user.id)


def test_get_goals_returns_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    get_goals = build_get_goals_service_mock(monkeypatch)
    get_goals.side_effect = GoalsNotFoundError

    response = client.get("/api/v1/profile/goals-and-constraints")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "GOALS_NOT_FOUND",
        "message": "Goals and constraints not found",
    }


def test_get_goals_returns_internal_state_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    get_goals = build_get_goals_service_mock(monkeypatch)
    get_goals.side_effect = GoalsStateError

    response = client.get("/api/v1/profile/goals-and-constraints")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "GOALS_STATE_INVALID",
        "message": "Goals and constraints state is invalid",
    }


def test_get_goals_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/profile/goals-and-constraints")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_update_goals_returns_created_resource(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    goal_id = uuid4()
    preferred_exercise_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    update_goals = build_goals_service_mock(monkeypatch)
    update_goals.return_value = GoalsUpdateResult(
        goal=UserGoal(
            id=goal_id,
            user_id=user.id,
            goal_type="muscle_gain",
            target_date=date(2027, 2, 1),
            target_weight_kg=Decimal("72.500"),
            status="active",
            version=1,
        ),
        constraints=UserConstraint(
            user_id=user.id,
            equipment=["barbell"],
            preferred_exercise_ids=[str(preferred_exercise_id)],
            disliked_exercise_ids=[],
            pain_or_injuries=[
                {
                    "kind": "current_pain",
                    "body_part": "left_knee",
                    "severity": 3,
                    "notes": "深蹲到底时不适",
                }
            ],
            allergies=["peanut"],
            dietary_preferences=[],
            version=1,
        ),
        warnings=[],
    )

    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={
            "goal_type": "muscle_gain",
            "target_date": "2027-02-01",
            "target_weight_kg": "72.500",
            "equipment": [" BARBELL "],
            "preferred_exercises": [str(preferred_exercise_id)],
            "pain_or_injuries": [
                {
                    "kind": "current_pain",
                    "body_part": "left_knee",
                    "severity": 3,
                    "notes": "深蹲到底时不适",
                }
            ],
            "allergies": ["peanut"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "version": 1,
        "goal": {
            "id": str(goal_id),
            "goal_type": "muscle_gain",
            "target_date": "2027-02-01",
            "target_weight_kg": "72.500",
            "status": "active",
        },
        "constraints": {
            "equipment": ["barbell"],
            "preferred_exercises": [str(preferred_exercise_id)],
            "disliked_exercises": [],
            "pain_or_injuries": [
                {
                    "kind": "current_pain",
                    "body_part": "left_knee",
                    "severity": 3,
                    "notes": "深蹲到底时不适",
                }
            ],
            "allergies": ["peanut"],
            "dietary_preferences": [],
        },
        "warnings": [],
    }
    call = update_goals.await_args
    assert call.kwargs["user_id"] == user.id
    assert call.kwargs["expected_version"] is None
    assert call.kwargs["data"].equipment == ["barbell"]
    assert call.kwargs["data"].preferred_exercises == [preferred_exercise_id]


def test_update_goals_requires_authentication(client: TestClient) -> None:
    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={"goal_type": "maintain", "equipment": []},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_update_goals_returns_version_required(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    update_goals = build_goals_service_mock(monkeypatch)
    update_goals.side_effect = GoalsVersionRequiredError

    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={"goal_type": "maintain", "equipment": []},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "GOALS_VERSION_REQUIRED",
        "message": "expected_version is required",
    }


def test_update_goals_returns_version_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    update_goals = build_goals_service_mock(monkeypatch)
    update_goals.side_effect = GoalsVersionConflictError(
        expected_version=1,
        current_version=2,
    )

    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={
            "goal_type": "strength",
            "equipment": ["barbell"],
            "expected_version": 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "GOALS_VERSION_CONFLICT",
        "message": "Goals and constraints have been modified",
        "details": {
            "expected_version": 1,
            "current_version": 2,
        },
    }


def test_update_goals_returns_internal_state_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    update_goals = build_goals_service_mock(monkeypatch)
    update_goals.side_effect = GoalsStateError

    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={
            "goal_type": "strength",
            "equipment": ["barbell"],
            "expected_version": 1,
        },
    )

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "GOALS_STATE_INVALID",
        "message": "Goals and constraints state is invalid",
    }


def test_update_goals_validates_request_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise_id = str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: user
    update_goals = build_goals_service_mock(monkeypatch)

    response = client.put(
        "/api/v1/profile/goals-and-constraints",
        json={
            "goal_type": "strength",
            "equipment": ["barbell"],
            "preferred_exercises": [exercise_id],
            "disliked_exercises": [exercise_id],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    update_goals.assert_not_awaited()
