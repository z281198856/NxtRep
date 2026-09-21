from datetime import UTC, datetime
from uuid import UUID

from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository


class AgentRunNotFoundError(RuntimeError):
    pass


class AgentRunConflictError(RuntimeError):
    pass


class AgentRunCancelledError(RuntimeError):
    pass


class AgentRunService:
    def __init__(self, repository: SqlAlchemyAgentRunRepository) -> None:
        self.repository = repository

    async def start(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        request_payload: dict,
    ) -> AgentRun:
        run = await self.repository.add(
            AgentRun(
                user_id=user_id,
                conversation_id=conversation_id,
                status="running",
                request_payload=request_payload,
                checkpoint={"node": "started"},
                started_at=datetime.now(UTC),
                version=1,
            )
        )
        await self.repository.commit()
        return run

    async def checkpoint(
        self,
        *,
        run: AgentRun,
        node: str,
        details: dict | None = None,
    ) -> AgentRun:
        await self.check_cancelled(run=run)
        run.checkpoint = {"node": node, "details": details or {}}
        run.version += 1
        await self.repository.commit()
        return run

    async def check_cancelled(self, *, run: AgentRun) -> AgentRun:
        """Refresh a running Agent run and stop execution when cancellation was requested."""
        await self.repository.refresh(run)
        if run.status == "cancel_requested":
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            run.version += 1
            await self.repository.commit()
            raise AgentRunCancelledError("Agent run was cancelled")
        if run.status == "cancelled":
            raise AgentRunCancelledError("Agent run was cancelled")
        return run

    async def abort(self, *, run: AgentRun, reason: str) -> AgentRun:
        """Close a non-terminal run when its stream consumer disappears."""
        await self.repository.refresh(run)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return run
        run.status = "cancelled"
        run.error_code = "AGENT_STREAM_CLOSED"
        run.error_message = reason[:500]
        run.checkpoint = {"node": "stream_closed", "details": {"reason": reason[:200]}}
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def succeed(self, *, run: AgentRun, result_payload: dict) -> AgentRun:
        run.status = "succeeded"
        run.result_payload = result_payload
        run.checkpoint = {"node": "completed"}
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def fail(self, *, run: AgentRun, error_code: str, error_message: str) -> AgentRun:
        run.status = "failed"
        run.error_code = error_code
        run.error_message = error_message[:2000]
        run.checkpoint = {"node": "failed"}
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def get(self, *, user_id: UUID, run_id: UUID) -> AgentRun:
        item = await self.repository.get_owned(user_id=user_id, run_id=run_id)
        if item is None:
            raise AgentRunNotFoundError("Agent run not found")
        return item

    async def request_cancel(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        expected_version: int,
    ) -> AgentRun:
        item = await self.repository.get_owned(
            user_id=user_id,
            run_id=run_id,
            lock=True,
        )
        if item is None:
            raise AgentRunNotFoundError("Agent run not found")
        if item.version != expected_version or item.status != "running":
            raise AgentRunConflictError("Agent run cannot be cancelled")
        item.status = "cancel_requested"
        item.version += 1
        await self.repository.flush()
        return item
