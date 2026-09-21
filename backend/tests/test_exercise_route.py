from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import exercise as exercise_route
from nxtrep_backend.db.models import Exercise, User
from nxtrep_backend.main import app
from nxtrep_backend.repositories.exercise import (
    ExerciseDetailRecord,
    ExerciseListEntry,
    ExerciseSubstitutionEntry,
)
from nxtrep_backend.services.exercise import (
    ExerciseCreateData,
    ExerciseListResult,
    ExerciseMuscleOverlapError,
    ExerciseNotFoundError,
    ExerciseStateError,
    ExerciseUpdateData,
    ExerciseVersionConflictError,
)
from nxtrep_backend.services.idempotency import (
    IdempotencyDecision,
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
    IdempotencyStateError,
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


def make_user() -> User:
    return User(
        id=uuid4(),
        username=f"exercise-route-{uuid4().hex}",
        password_setup_required=False,
    )


def build_list_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    list_exercises = AsyncMock()
    service = MagicMock()
    service.list_exercises = list_exercises
    monkeypatch.setattr(
        exercise_route,
        "ExercisesService",
        MagicMock(return_value=service),
    )
    return list_exercises


def build_detail_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    get_exercise_detail = AsyncMock()
    service = MagicMock()
    service.get_exercise_detail = get_exercise_detail
    monkeypatch.setattr(
        exercise_route,
        "ExercisesService",
        MagicMock(return_value=service),
    )
    return get_exercise_detail


def build_create_service_mocks(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    create_custom_exercise = AsyncMock()
    exercise_service = MagicMock()
    exercise_service.create_custom_exercise = create_custom_exercise
    monkeypatch.setattr(
        exercise_route,
        "ExercisesService",
        MagicMock(return_value=exercise_service),
    )

    begin = AsyncMock()
    complete = AsyncMock()
    idempotency_service = MagicMock()
    idempotency_service.begin = begin
    idempotency_service.complete = complete
    monkeypatch.setattr(
        exercise_route,
        "IdempotencyService",
        MagicMock(return_value=idempotency_service),
    )

    return create_custom_exercise, begin, complete


def build_update_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    update_custom_exercise = AsyncMock()
    service = MagicMock()
    service.update_custom_exercise = update_custom_exercise
    monkeypatch.setattr(
        exercise_route,
        "ExercisesService",
        MagicMock(return_value=service),
    )
    return update_custom_exercise


def build_delete_service_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    delete_custom_exercise = AsyncMock()
    service = MagicMock()
    service.delete_custom_exercise = delete_custom_exercise
    monkeypatch.setattr(
        exercise_route,
        "ExercisesService",
        MagicMock(return_value=service),
    )
    return delete_custom_exercise


def make_custom_detail(user_id: UUID) -> ExerciseDetailRecord:
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=user_id,
        name_zh="高脚杯深蹲",
        movement_pattern=None,
        equipment="dumbbell",
        difficulty=None,
        instructions=[],
        breathing=[],
        common_errors=[],
        safety_notes=[],
        notes="家里训练使用",
        version=1,
    )
    return ExerciseDetailRecord(
        exercise=exercise,
        aliases=[],
        primary_muscles=["quadriceps", "gluteus"],
        secondary_muscles=[],
        substitutions=[],
    )


def test_list_exercises_returns_paginated_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=None,
        name_zh="杠铃深蹲",
        equipment="barbell",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    list_exercises = build_list_service_mock(monkeypatch)
    list_exercises.return_value = ExerciseListResult(
        items=[
            ExerciseListEntry(
                exercise=exercise,
                aliases=["深蹲"],
                primary_muscles=["quadriceps", "gluteus"],
            )
        ],
        total=21,
        page=2,
        page_size=20,
        has_more=False,
    )

    response = client.get(
        "/api/v1/exercises",
        params={
            "keyword": "  深蹲  ",
            "equipment": "barbell",
            "muscle": "quadriceps",
            "page": 2,
            "page_size": 20,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "list": [
            {
                "id": str(exercise.id),
                "name_zh": "杠铃深蹲",
                "aliases": ["深蹲"],
                "equipment": "barbell",
                "primary_muscles": ["quadriceps", "gluteus"],
                "is_custom": False,
            }
        ],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "has_more": False,
    }
    list_exercises.assert_awaited_once_with(
        user_id=user.id,
        keyword="深蹲",
        equipment="barbell",
        muscle="quadriceps",
        page=2,
        page_size=20,
    )


def test_list_exercises_uses_query_defaults(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    list_exercises = build_list_service_mock(monkeypatch)
    list_exercises.return_value = ExerciseListResult(
        items=[],
        total=0,
        page=1,
        page_size=20,
        has_more=False,
    )

    response = client.get("/api/v1/exercises")

    assert response.status_code == 200
    list_exercises.assert_awaited_once_with(
        user_id=user.id,
        keyword=None,
        equipment=None,
        muscle=None,
        page=1,
        page_size=20,
    )


def test_list_exercises_rejects_invalid_pagination_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    list_exercises = build_list_service_mock(monkeypatch)

    response = client.get(
        "/api/v1/exercises",
        params={"page_size": 101},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    list_exercises.assert_not_awaited()


def test_list_exercises_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/exercises")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_exercise_list_is_registered_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "get" in schema["paths"]["/api/v1/exercises"]


def test_get_exercise_detail_returns_complete_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise = Exercise(
        id=uuid4(),
        owner_user_id=None,
        name_zh="杠铃深蹲",
        movement_pattern="squat",
        equipment="barbell",
        difficulty="intermediate",
        instructions=["收紧核心"],
        breathing=["下蹲时吸气"],
        common_errors=["膝盖内扣"],
        safety_notes=["出现疼痛时停止"],
        notes=None,
        version=1,
    )
    target = Exercise(
        id=uuid4(),
        owner_user_id=user.id,
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    get_detail = build_detail_service_mock(monkeypatch)
    get_detail.return_value = ExerciseDetailRecord(
        exercise=exercise,
        aliases=["深蹲"],
        primary_muscles=["quadriceps", "gluteus"],
        secondary_muscles=["hamstring"],
        substitutions=[
            ExerciseSubstitutionEntry(
                exercise=target,
                reason="无杠铃时可替代",
            )
        ],
    )

    response = client.get(f"/api/v1/exercises/{exercise.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(exercise.id),
        "name_zh": "杠铃深蹲",
        "aliases": ["深蹲"],
        "movement_pattern": "squat",
        "equipment": "barbell",
        "difficulty": "intermediate",
        "primary_muscles": ["quadriceps", "gluteus"],
        "secondary_muscles": ["hamstring"],
        "instructions": ["收紧核心"],
        "breathing": ["下蹲时吸气"],
        "common_errors": ["膝盖内扣"],
        "safety_notes": ["出现疼痛时停止"],
        "substitutions": [
            {
                "id": str(target.id),
                "name_zh": "高脚杯深蹲",
                "equipment": "dumbbell",
                "reason": "无杠铃时可替代",
            }
        ],
        "notes": None,
        "version": 1,
        "is_custom": False,
    }
    get_detail.assert_awaited_once_with(
        user_id=user.id,
        exercise_id=exercise.id,
    )


def test_get_exercise_detail_returns_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    get_detail = build_detail_service_mock(monkeypatch)
    get_detail.side_effect = ExerciseNotFoundError

    response = client.get(f"/api/v1/exercises/{exercise_id}")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "EXERCISE_NOT_FOUND",
        "message": "Exercise not found",
    }


def test_get_exercise_detail_rejects_invalid_uuid_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    get_detail = build_detail_service_mock(monkeypatch)

    response = client.get("/api/v1/exercises/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    get_detail.assert_not_awaited()


def test_get_exercise_detail_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/exercises/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_exercise_detail_is_registered_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "get" in schema["paths"]["/api/v1/exercises/{exercise_id}"]


def test_create_custom_exercise_executes_once_and_stores_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    idempotency_key = uuid4()
    detail = make_custom_detail(user.id)
    app.dependency_overrides[get_current_user] = lambda: user
    create_exercise, begin, complete = build_create_service_mocks(monkeypatch)
    decision = IdempotencyDecision(
        record_id=uuid4(),
        replayed=False,
        response_status=None,
        response_body=None,
    )
    begin.return_value = decision
    create_exercise.return_value = detail

    response = client.post(
        "/api/v1/exercises",
        headers={"Idempotency-Key": str(idempotency_key)},
        json={
            "name_zh": "  高脚杯深蹲  ",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps", "gluteus"],
            "notes": "  家里训练使用  ",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(detail.exercise.id)
    assert response.json()["is_custom"] is True
    begin.assert_awaited_once_with(
        user_id=user.id,
        idempotency_key=idempotency_key,
        operation="POST /exercises",
        payload={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps", "gluteus"],
            "secondary_muscles": [],
            "notes": "家里训练使用",
        },
    )
    create_call = create_exercise.await_args
    assert create_call.kwargs["user_id"] == user.id
    assert create_call.kwargs["data"] == ExerciseCreateData(
        name_zh="高脚杯深蹲",
        equipment="dumbbell",
        primary_muscles=["quadriceps", "gluteus"],
        secondary_muscles=[],
        notes="家里训练使用",
    )
    complete.assert_awaited_once_with(
        decision=decision,
        response_status=201,
        response_body=response.json(),
    )


def test_create_custom_exercise_replays_without_creating_again(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    detail = make_custom_detail(user.id)
    stored_response = exercise_route._build_exercise_detail_response(detail).model_dump(mode="json")
    app.dependency_overrides[get_current_user] = lambda: user
    create_exercise, begin, complete = build_create_service_mocks(monkeypatch)
    begin.return_value = IdempotencyDecision(
        record_id=uuid4(),
        replayed=True,
        response_status=201,
        response_body=stored_response,
    )

    response = client.post(
        "/api/v1/exercises",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps", "gluteus"],
            "notes": "家里训练使用",
        },
    )

    assert response.status_code == 201
    assert response.json() == stored_response
    create_exercise.assert_not_awaited()
    complete.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (
            IdempotencyKeyConflictError(),
            409,
            "IDEMPOTENCY_KEY_CONFLICT",
        ),
        (
            IdempotencyRequestInProgressError(),
            409,
            "IDEMPOTENCY_REQUEST_IN_PROGRESS",
        ),
        (
            IdempotencyStateError(),
            500,
            "IDEMPOTENCY_STATE_INVALID",
        ),
    ],
)
def test_create_custom_exercise_maps_idempotency_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    create_exercise, begin, complete = build_create_service_mocks(monkeypatch)
    begin.side_effect = error

    response = client.post(
        "/api/v1/exercises",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps"],
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    create_exercise.assert_not_awaited()
    complete.assert_not_awaited()


def test_create_custom_exercise_requires_idempotency_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    create_exercise, begin, complete = build_create_service_mocks(monkeypatch)

    response = client.post(
        "/api/v1/exercises",
        json={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    begin.assert_not_awaited()
    create_exercise.assert_not_awaited()
    complete.assert_not_awaited()


def test_create_custom_exercise_validates_body_before_services(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    create_exercise, begin, complete = build_create_service_mocks(monkeypatch)

    response = client.post(
        "/api/v1/exercises",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    begin.assert_not_awaited()
    create_exercise.assert_not_awaited()
    complete.assert_not_awaited()


def test_create_custom_exercise_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/exercises",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "primary_muscles": ["quadriceps"],
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_update_custom_exercise_preserves_partial_update_semantics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    detail = make_custom_detail(user.id)
    detail.exercise.name_zh = "新动作名称"
    detail.exercise.notes = None
    detail.exercise.version = 3
    app.dependency_overrides[get_current_user] = lambda: user
    update_exercise = build_update_service_mock(monkeypatch)
    update_exercise.return_value = detail

    response = client.patch(
        f"/api/v1/exercises/{detail.exercise.id}",
        json={
            "name_zh": "  新动作名称  ",
            "notes": None,
            "expected_version": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["name_zh"] == "新动作名称"
    assert response.json()["notes"] is None
    assert response.json()["version"] == 3
    update_exercise.assert_awaited_once_with(
        user_id=user.id,
        exercise_id=detail.exercise.id,
        data=ExerciseUpdateData(
            name_zh="新动作名称",
            equipment=None,
            primary_muscles=None,
            secondary_muscles=None,
            notes=None,
            supplied_fields=frozenset({"name_zh", "notes"}),
        ),
        expected_version=2,
    )


def test_update_custom_exercise_returns_version_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    update_exercise = build_update_service_mock(monkeypatch)
    update_exercise.side_effect = ExerciseVersionConflictError(
        expected_version=2,
        current_version=3,
    )

    response = client.patch(
        f"/api/v1/exercises/{exercise_id}",
        json={"name_zh": "新名称", "expected_version": 2},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "EXERCISE_VERSION_CONFLICT",
        "message": "Exercise has been modified",
        "details": {
            "expected_version": 2,
            "current_version": 3,
        },
    }


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ExerciseNotFoundError(), 404, "EXERCISE_NOT_FOUND"),
        (
            ExerciseMuscleOverlapError(),
            409,
            "EXERCISE_MUSCLE_CONFLICT",
        ),
        (ExerciseStateError(), 500, "EXERCISE_STATE_INVALID"),
    ],
)
def test_update_custom_exercise_maps_business_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    update_exercise = build_update_service_mock(monkeypatch)
    update_exercise.side_effect = error

    response = client.patch(
        f"/api/v1/exercises/{uuid4()}",
        json={"name_zh": "新名称", "expected_version": 2},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_update_custom_exercise_validates_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    update_exercise = build_update_service_mock(monkeypatch)

    response = client.patch(
        f"/api/v1/exercises/{uuid4()}",
        json={"expected_version": 2},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    update_exercise.assert_not_awaited()


def test_update_custom_exercise_requires_authentication(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/exercises/{uuid4()}",
        json={"name_zh": "新名称", "expected_version": 2},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_exercise_update_is_registered_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "patch" in schema["paths"]["/api/v1/exercises/{exercise_id}"]


def test_delete_custom_exercise_returns_no_content(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    delete_exercise = build_delete_service_mock(monkeypatch)

    response = client.delete(
        f"/api/v1/exercises/{exercise_id}",
        params={"expected_version": 2},
    )

    assert response.status_code == 204
    assert response.content == b""
    delete_exercise.assert_awaited_once_with(
        user_id=user.id,
        exercise_id=exercise_id,
        expected_version=2,
    )


def test_delete_custom_exercise_returns_version_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    exercise_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    delete_exercise = build_delete_service_mock(monkeypatch)
    delete_exercise.side_effect = ExerciseVersionConflictError(
        expected_version=2,
        current_version=3,
    )

    response = client.delete(
        f"/api/v1/exercises/{exercise_id}",
        params={"expected_version": 2},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "EXERCISE_VERSION_CONFLICT",
        "message": "Exercise has been modified",
        "details": {
            "expected_version": 2,
            "current_version": 3,
        },
    }


def test_delete_custom_exercise_returns_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    delete_exercise = build_delete_service_mock(monkeypatch)
    delete_exercise.side_effect = ExerciseNotFoundError

    response = client.delete(
        f"/api/v1/exercises/{uuid4()}",
        params={"expected_version": 1},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EXERCISE_NOT_FOUND"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"expected_version": 0},
    ],
)
def test_delete_custom_exercise_validates_expected_version_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, int],
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    delete_exercise = build_delete_service_mock(monkeypatch)

    response = client.delete(
        f"/api/v1/exercises/{uuid4()}",
        params=params,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    delete_exercise.assert_not_awaited()


def test_delete_custom_exercise_requires_authentication(client: TestClient) -> None:
    response = client.delete(
        f"/api/v1/exercises/{uuid4()}",
        params={"expected_version": 1},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_exercise_delete_is_registered_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "delete" in schema["paths"]["/api/v1/exercises/{exercise_id}"]
