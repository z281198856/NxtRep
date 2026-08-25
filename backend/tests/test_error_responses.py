from fastapi.testclient import TestClient

from nxtrep_backend.main import app


def test_missing_authentication_uses_standard_error_response() -> None:
    response = TestClient(app).post(
        "/api/v1/agent/chat",
        json={"message": "今天练什么？"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Bearer access token is required",
        }
    }
    assert response.headers["www-authenticate"] == "Bearer"


def test_unknown_route_uses_standard_error_response() -> None:
    response = TestClient(app).get("/api/v1/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Not Found",
        }
    }
