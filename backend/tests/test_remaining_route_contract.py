from nxtrep_backend.main import app

DOCUMENTED_ENDPOINTS = {
    ("get", "/api/v1/training/templates"),
    ("post", "/api/v1/training/plan-drafts"),
    ("post", "/api/v1/training/plan-drafts/from-template"),
    ("get", "/api/v1/training/plan-drafts/{draft_id}"),
    ("patch", "/api/v1/training/plan-drafts/{draft_id}"),
    ("post", "/api/v1/training/plan-drafts/{draft_id}/validate"),
    ("post", "/api/v1/training/plan-drafts/{draft_id}/submit"),
    ("get", "/api/v1/training/plans/active"),
    ("get", "/api/v1/training/plans/{plan_id}/versions"),
    ("get", "/api/v1/calendar"),
    ("post", "/api/v1/calendar/reschedule-drafts"),
    ("post", "/api/v1/calendar/reschedule-drafts/{draft_id}/submit"),
    ("post", "/api/v1/workouts"),
    ("get", "/api/v1/workouts/active"),
    ("get", "/api/v1/workouts"),
    ("get", "/api/v1/workouts/{workout_id}"),
    ("post", "/api/v1/workouts/{workout_id}/sets"),
    ("patch", "/api/v1/workouts/{workout_id}/sets/{set_id}"),
    ("post", "/api/v1/workouts/{workout_id}/exercises/{item_id}/replace"),
    ("post", "/api/v1/workouts/{workout_id}/finish"),
    ("post", "/api/v1/workouts/{workout_id}/progression-drafts"),
    ("post", "/api/v1/workouts/{workout_id}/progression-drafts/{draft_id}/submit"),
    ("get", "/api/v1/foods/search"),
    ("post", "/api/v1/foods"),
    ("post", "/api/v1/nutrition/entries"),
    ("get", "/api/v1/nutrition/entries"),
    ("patch", "/api/v1/nutrition/entries/{entry_id}"),
    ("get", "/api/v1/nutrition/daily-summary"),
    ("post", "/api/v1/nutrition/target-drafts"),
    ("post", "/api/v1/nutrition/target-drafts/{target_id}/submit"),
    ("post", "/api/v1/body/measurements"),
    ("get", "/api/v1/body/measurements"),
    ("patch", "/api/v1/body/measurements/{measurement_id}"),
    ("post", "/api/v1/body/body-fat/navy"),
    ("get", "/api/v1/progress/overview"),
    ("get", "/api/v1/progress/body-trend"),
    ("get", "/api/v1/progress/prs"),
    ("get", "/api/v1/confirmations"),
    ("post", "/api/v1/confirmations/{confirmation_id}/approve"),
    ("post", "/api/v1/confirmations/{confirmation_id}/reject"),
}

IDEMPOTENT_ENDPOINTS = {
    ("post", "/api/v1/training/plan-drafts"),
    ("post", "/api/v1/training/plan-drafts/from-template"),
    ("post", "/api/v1/training/plan-drafts/{draft_id}/submit"),
    ("post", "/api/v1/calendar/reschedule-drafts"),
    ("post", "/api/v1/calendar/reschedule-drafts/{draft_id}/submit"),
    ("post", "/api/v1/workouts"),
    ("post", "/api/v1/workouts/{workout_id}/sets"),
    ("post", "/api/v1/workouts/{workout_id}/finish"),
    ("post", "/api/v1/workouts/{workout_id}/progression-drafts"),
    ("post", "/api/v1/workouts/{workout_id}/progression-drafts/{draft_id}/submit"),
    ("post", "/api/v1/foods"),
    ("post", "/api/v1/nutrition/entries"),
    ("post", "/api/v1/nutrition/target-drafts"),
    ("post", "/api/v1/nutrition/target-drafts/{target_id}/submit"),
    ("post", "/api/v1/body/measurements"),
    ("post", "/api/v1/confirmations/{confirmation_id}/approve"),
}


def test_all_documented_non_agent_endpoints_are_registered() -> None:
    schema = app.openapi()
    actual = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "patch", "delete"}
    }
    assert DOCUMENTED_ENDPOINTS <= actual


def test_documented_idempotent_commands_require_header() -> None:
    schema = app.openapi()
    for method, path in IDEMPOTENT_ENDPOINTS:
        parameters = schema["paths"][path][method].get("parameters", [])
        header = next(
            (
                item
                for item in parameters
                if item["in"] == "header" and item["name"] == "Idempotency-Key"
            ),
            None,
        )
        assert header is not None, (method, path)
        assert header["required"] is True


def test_agent_routes_include_chat_conversation_and_run_management() -> None:
    schema = app.openapi()
    agent_paths = {path for path in schema["paths"] if "/agent/" in path}
    assert agent_paths == {
        "/api/v1/agent/chat",
        "/api/v1/agent/chat/stream",
        "/api/v1/agent/conversations",
        "/api/v1/agent/conversations/{conversation_id}",
        "/api/v1/agent/conversations/{conversation_id}/messages",
        "/api/v1/agent/proactive/review",
        "/api/v1/agent/runs/{run_id}",
        "/api/v1/agent/runs/{run_id}:cancel",
        "/api/v1/agent/tool-runs",
    }
