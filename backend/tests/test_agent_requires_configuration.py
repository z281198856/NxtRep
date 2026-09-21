from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nxtrep_backend.api.deps import get_current_user_id
from nxtrep_backend.core.config import Settings
from nxtrep_backend.main import app
from nxtrep_backend.providers.models import build_vision_model


def test_agent_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    settings = Settings(
        _env_file=None,
        rag_enabled=False,
        llm_provider="deepseek",
        deepseek_api_key=None,
        glm_api_key=None,
    )
    monkeypatch.setattr("nxtrep_backend.agents.factory.get_settings", lambda: settings)
    monkeypatch.setattr(
        "nxtrep_backend.agents.factory.build_image_storage_provider",
        MagicMock(),
    )

    try:
        response = TestClient(app).post(
            "/api/v1/agent/chat",
            json={"message": "今天练什么？"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_NOT_CONFIGURED"
    assert "DEEPSEEK_API_KEY" in response.json()["error"]["message"]


def test_vision_model_requires_glm_api_key() -> None:
    settings = Settings(_env_file=None, glm_api_key=None)

    with pytest.raises(ValueError, match="NXTREP_GLM_API_KEY"):
        build_vision_model(settings)
