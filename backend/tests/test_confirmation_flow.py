from uuid import uuid4

from fastapi.testclient import TestClient

from nxtrep_backend.api.deps import get_current_user_id
from nxtrep_backend.main import app


def test_confirmation_is_isolated_by_user() -> None:
    client = TestClient(app)
    owner_id = uuid4()
    other_id = uuid4()

    try:
        app.dependency_overrides[get_current_user_id] = lambda: owner_id
        created = client.post(
            "/api/v1/confirmations",
            json={
                "operation": "training.plan.activate",
                "before": None,
                "after": {"plan_version_id": "version-2"},
                "reason": "用户请求激活新的训练计划",
                "impact": "后续日历将使用新版本，历史训练不变",
            },
        )

        assert created.status_code == 201
        confirmation_id = created.json()["id"]

        app.dependency_overrides[get_current_user_id] = lambda: other_id
        forbidden_as_not_found = client.post(
            f"/api/v1/confirmations/{confirmation_id}/decision",
            json={"decision": "approve"},
        )
        assert forbidden_as_not_found.status_code == 404

        app.dependency_overrides[get_current_user_id] = lambda: owner_id
        approved = client.post(
            f"/api/v1/confirmations/{confirmation_id}/decision",
            json={"decision": "approve"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
