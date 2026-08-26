from nxtrep_backend.main import app


def test_legacy_in_memory_confirmation_commands_are_not_public_routes() -> None:
    paths = app.openapi()["paths"]
    assert "post" not in paths["/api/v1/confirmations"]
    assert "/api/v1/confirmations/{confirmation_id}/decision" not in paths
