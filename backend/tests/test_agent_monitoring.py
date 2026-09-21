import logging
from uuid import uuid4

from nxtrep_backend.services.agent_monitoring import AgentRunMonitor


def test_monitor_emits_safe_structured_lifecycle_fields(caplog) -> None:
    run_id = uuid4()
    conversation_id = uuid4()
    monitor = AgentRunMonitor()

    with caplog.at_level(logging.INFO, logger="nxtrep.agent"):
        monitor.run_started(run_id=run_id, conversation_id=conversation_id)
        monitor.node_completed(
            run_id=run_id,
            node="plan_request",
            total_elapsed_ms=120,
            node_elapsed_ms=120,
        )
        monitor.run_succeeded(run_id=run_id, duration_ms=450)

    assert [record.agent_event for record in caplog.records] == [
        "agent_run_started",
        "agent_node_completed",
        "agent_run_succeeded",
    ]
    assert all(record.agent_run_id == str(run_id) for record in caplog.records)
    assert "plan_request" in caplog.text
    assert "user message" not in caplog.text
