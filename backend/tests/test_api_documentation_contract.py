import json
import re
from pathlib import Path

from nxtrep_backend.main import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ENDPOINT_ROW = re.compile(
    r"\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`",
)


def _normalize_path(path: str) -> str:
    if not path.startswith("/api/") and path != "/health":
        path = f"/api/v1{path}"
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_development_plan_lists_every_public_openapi_operation_exactly() -> None:
    project_root = Path(__file__).resolve().parents[2]
    document = (project_root / "docs" / "BACKEND_DEVELOPMENT_PLAN.md").read_text(
        encoding="utf-8"
    )
    documented = {
        (match.group(1).lower(), _normalize_path(match.group(2)))
        for match in ENDPOINT_ROW.finditer(document)
    }

    schema = app.openapi()
    exposed = {
        (method, _normalize_path(path))
        for path, operations in schema["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }

    assert documented == exposed


def test_workout_timer_openapi_contract_is_documented_by_schema() -> None:
    schema = app.openapi()
    response_properties = schema["components"]["schemas"]["WorkoutResponse"]["properties"]

    assert {
        "paused_at",
        "total_paused_seconds",
        "elapsed_seconds",
        "rest_timer",
    } <= response_properties.keys()
    assert "post" in schema["paths"]["/api/v1/workouts/{workout_id}/resume"]
    assert "WorkoutResumeRequest" in schema["components"]["schemas"]


def test_openapi_documents_every_success_response_contract() -> None:
    schema = app.openapi()
    missing_contracts: list[str] = []

    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            for status_code, response in operation["responses"].items():
                if not status_code.startswith("2") or status_code == "204":
                    continue
                content = response.get("content", {})
                if not content or not all(
                    media.get("schema") for media in content.values()
                ):
                    missing_contracts.append(f"{method.upper()} {path} -> {status_code}")

    assert missing_contracts == []


def test_mobile_contracts_are_visible_in_openapi() -> None:
    schema = app.openapi()
    token_fields = schema["components"]["schemas"]["TokenPairResponse"]["properties"]
    assert {"expires_in", "refresh_expires_in"} <= token_fields.keys()

    capabilities = schema["components"]["schemas"]["ImageUploadCapabilitiesResponse"]
    assert "convert_before_upload" in capabilities["properties"]

    for path in (
        "/api/v1/agent/chat/stream",
        "/api/v1/agent/conversations/{conversation_id}/messages",
    ):
        content = schema["paths"][path]["post"]["responses"]["200"]["content"]
        assert "text/event-stream" in content


def test_openapi_never_exposes_database_connection_configuration() -> None:
    serialized = json.dumps(app.openapi()).lower()

    assert "database_url" not in serialized
    assert "postgresql+asyncpg://" not in serialized


def test_openapi_documents_the_runtime_error_envelope() -> None:
    schema = app.openapi()

    for operations in schema["paths"].values():
        for method, operation in operations.items():
            if method not in HTTP_METHODS or not operation.get("security"):
                continue
            default_schema = operation["responses"]["default"]["content"][
                "application/json"
            ]["schema"]
            validation_schema = operation["responses"]["422"]["content"][
                "application/json"
            ]["schema"]
            assert default_schema["$ref"].endswith("/ErrorResponse")
            assert validation_schema["$ref"].endswith("/ErrorResponse")
