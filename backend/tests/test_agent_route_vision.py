from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.agents.intent_router import AgentIntentRoutingError
from nxtrep_backend.agents.synthesis import AgentResponseSynthesisError
from nxtrep_backend.api.deps import get_current_user_id
from nxtrep_backend.api.routes import agent as agent_route
from nxtrep_backend.core.config import StorageConfigurationError
from nxtrep_backend.db.session import get_db_session
from nxtrep_backend.main import app
from nxtrep_backend.providers.models import ModelConfigurationError
from nxtrep_backend.providers.storage import StorageProviderError
from nxtrep_backend.schemas.agent import AgentChatResponse, AgentStreamEvent
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
)
from nxtrep_backend.services.agent_workflow import AgentWorkflowResultError


@pytest.fixture
def client() -> Iterator[tuple[TestClient, MagicMock]]:
    session = MagicMock(spec=AsyncSession)

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides.pop(get_current_user_id, None)

    with TestClient(app) as test_client:
        yield test_client, session

    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_current_user_id, None)


def build_route_mocks(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock]:
    service = MagicMock()
    service.chat = AsyncMock()
    service_factory = MagicMock(return_value=service)
    monkeypatch.setattr(
        agent_route,
        "build_agent_workflow_service",
        service_factory,
    )
    return service, service_factory


def test_text_chat_uses_agent_workflow(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session = client
    user_id = uuid4()
    conversation_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    service, service_factory = build_route_mocks(monkeypatch)
    service.chat.return_value = AgentChatResponse(
        message="文字回答",
        conversation_id=conversation_id,
    )

    response = test_client.post(
        "/api/v1/agent/chat",
        json={"message": "今天练什么？"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "文字回答",
        "conversation_id": str(conversation_id),
        "run_id": None,
        "status": "completed",
        "analysis_results": [],
        "confirmation_cards": [],
        "citations": [],
    }
    service_factory.assert_called_once_with(
        session=session,
        user_id=user_id,
    )
    request = service.chat.await_args.kwargs["request"]
    assert request.message == "今天练什么？"
    assert request.image_asset_ids == []
    service.chat.assert_awaited_once_with(
        user_id=user_id,
        request=request,
    )


def test_image_chat_passes_all_asset_ids_to_workflow(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session = client
    user_id = uuid4()
    body_asset_id = uuid4()
    food_asset_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    service, service_factory = build_route_mocks(monkeypatch)
    service.chat.return_value = AgentChatResponse(
        message="体态和饮食分析结果",
        conversation_id=uuid4(),
    )

    response = test_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "分析我的体态和这顿饭",
            "image_asset_ids": [
                str(body_asset_id),
                str(food_asset_id),
            ],
        },
    )

    assert response.status_code == 200
    service_factory.assert_called_once_with(
        session=session,
        user_id=user_id,
    )
    request = service.chat.await_args.kwargs["request"]
    assert request.image_asset_ids == [
        body_asset_id,
        food_asset_id,
    ]


def test_stream_chat_returns_sse_events(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _session = client
    user_id = uuid4()
    run_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    service, _factory = build_route_mocks(monkeypatch)

    async def events():
        yield AgentStreamEvent(event="run_started", run_id=run_id)
        yield AgentStreamEvent(
            event="message_delta",
            run_id=run_id,
            node="synthesize_response",
            delta="你好",
            sequence=1,
        )
        yield AgentStreamEvent(
            event="failed",
            run_id=run_id,
            error_code="MODEL_TIMEOUT",
            message="Agent execution failed",
        )

    service.stream = MagicMock(return_value=events())

    response = test_client.post(
        "/api/v1/agent/chat/stream",
        json={"message": "给我训练建议"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: run_started" in response.text
    assert response.text.count("event: message_delta") == 2
    assert '"delta":"你"' in response.text
    assert '"delta":"好"' in response.text
    assert "event: failed" in response.text
    assert str(run_id) in response.text


def test_stream_chat_can_preserve_model_chunks(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _session = client
    app.dependency_overrides[get_current_user_id] = lambda: uuid4()
    service, _factory = build_route_mocks(monkeypatch)

    async def events():
        yield AgentStreamEvent(
            event="message_delta",
            delta="你好",
            sequence=1,
        )

    service.stream = MagicMock(return_value=events())

    response = test_client.post(
        "/api/v1/agent/chat/stream?granularity=chunk",
        json={"message": "给我训练建议"},
    )

    assert response.status_code == 200
    assert response.text.count("event: message_delta") == 1
    assert '"delta":"你好"' in response.text


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (
            AgentImageAssetNotFoundError(),
            404,
            "IMAGE_ASSET_NOT_FOUND",
        ),
        (
            AgentImageAssetNotReadyError(),
            409,
            "IMAGE_ASSET_NOT_READY",
        ),
        (
            StorageProviderError(),
            503,
            "IMAGE_STORAGE_UNAVAILABLE",
        ),
        (
            AgentIntentRoutingError(),
            502,
            "AGENT_INVALID_MODEL_RESPONSE",
        ),
        (
            AgentResponseSynthesisError(),
            502,
            "AGENT_INVALID_MODEL_RESPONSE",
        ),
        (
            AgentWorkflowResultError(),
            502,
            "AGENT_INVALID_MODEL_RESPONSE",
        ),
        (
            ModelConfigurationError("missing model key"),
            503,
            "AGENT_NOT_CONFIGURED",
        ),
        (
            StorageConfigurationError("missing OSS config"),
            503,
            "AGENT_NOT_CONFIGURED",
        ),
    ],
)
def test_chat_maps_workflow_errors(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    test_client, _ = client
    app.dependency_overrides[get_current_user_id] = lambda: uuid4()
    service, _ = build_route_mocks(monkeypatch)
    service.chat.side_effect = error

    response = test_client.post(
        "/api/v1/agent/chat",
        json={
            "message": "分析图片",
            "image_asset_ids": [str(uuid4())],
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
