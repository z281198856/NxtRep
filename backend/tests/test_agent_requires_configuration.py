from uuid import uuid4

from fastapi.testclient import TestClient

from nxtrep_backend.api.deps import get_current_user_id
from nxtrep_backend.main import app


def test_agent_requires_api_key() -> None:
    user_id = uuid4()
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    try:
        response = TestClient(app).post(
            "/api/v1/agent/chat",
            json={"message": "今天练什么？"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_NOT_CONFIGURED"
    assert "OPENAI_API_KEY" in response.json()["error"]["message"]
