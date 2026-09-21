import logging
from uuid import UUID

logger = logging.getLogger("nxtrep.agent")


class AgentRunMonitor:
    """Emit privacy-minimized lifecycle records for Agent runs."""

    def run_started(self, *, run_id: UUID, conversation_id: UUID) -> None:
        self._emit(
            logging.INFO,
            "agent_run_started",
            run_id=run_id,
            conversation_id=conversation_id,
        )

    def node_completed(
        self,
        *,
        run_id: UUID,
        node: str,
        total_elapsed_ms: int,
        node_elapsed_ms: int,
    ) -> None:
        self._emit(
            logging.INFO,
            "agent_node_completed",
            run_id=run_id,
            node=node,
            total_elapsed_ms=total_elapsed_ms,
            node_elapsed_ms=node_elapsed_ms,
        )

    def run_succeeded(self, *, run_id: UUID, duration_ms: int) -> None:
        self._emit(
            logging.INFO,
            "agent_run_succeeded",
            run_id=run_id,
            duration_ms=duration_ms,
        )

    def run_cancelled(self, *, run_id: UUID, duration_ms: int, reason: str) -> None:
        self._emit(
            logging.INFO,
            "agent_run_cancelled",
            run_id=run_id,
            duration_ms=duration_ms,
            reason=reason,
        )

    def run_failed(self, *, run_id: UUID, duration_ms: int, error_code: str) -> None:
        self._emit(
            logging.WARNING,
            "agent_run_failed",
            run_id=run_id,
            duration_ms=duration_ms,
            error_code=error_code,
        )

    @staticmethod
    def _emit(level: int, event: str, *, run_id: UUID, **fields: object) -> None:
        normalized_fields = {
            key: str(value) if isinstance(value, UUID) else value for key, value in fields.items()
        }
        safe_fields = {
            "agent_event": event,
            "agent_run_id": str(run_id),
            **normalized_fields,
        }
        logger.log(
            level,
            "%s run_id=%s fields=%s",
            event,
            run_id,
            normalized_fields,
            extra=safe_fields,
        )
