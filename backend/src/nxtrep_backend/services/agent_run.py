from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository


class AgentRunNotFoundError(RuntimeError):
    pass


class AgentRunConflictError(RuntimeError):
    pass


class AgentRunCancelledError(RuntimeError):
    pass


class AgentRunInProgressError(RuntimeError):
    """A different turn already owns this conversation's execution slot."""


class AgentRunService:
    def __init__(
        self,
        repository: SqlAlchemyAgentRunRepository,
        *,
        stale_after_seconds: float = 600,
    ) -> None:
        if stale_after_seconds < 180:
            raise ValueError("stale_after_seconds must allow at least 180 seconds")
        self.repository = repository
        self._stale_after = timedelta(seconds=stale_after_seconds)

    async def ensure_available(self, user_id: UUID, conversation_id: UUID) -> None:
        if not await self.repository.lock_conversation(user_id, conversation_id):
            raise AgentRunNotFoundError("未找到当前对话，请重新打开对话。")
        active = await self.repository.list_active(user_id, conversation_id)
        now = datetime.now(UTC)
        # Check all entries before changing any, including legacy overlapping runs.
        if any(
            item.started_at is None or now - item.started_at < self._stale_after for item in active
        ):
            raise AgentRunInProgressError("这段对话的上一条请求仍在处理中，请等待结果后继续。")
        for item in active:
            item.status = "failed"
            item.error_code = "AGENT_RUN_INTERRUPTED"
            item.error_message = "上一次处理已中断，请核对已生成的草稿或记录后继续。"
            item.checkpoint = {**(item.checkpoint or {}), "node": "interrupted"}
            item.finished_at = now
            item.version += 1
        if active:
            await self.repository.flush()

    async def start(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        request_payload: dict,
    ) -> AgentRun:
        try:
            await self.ensure_available(user_id, conversation_id)
        except (AgentRunInProgressError, AgentRunNotFoundError):
            # Legacy callers may already have appended a user message. A denied
            # turn must not leave it behind if the transport catches this error.
            await self.repository.rollback()
            raise
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
        journal: dict | None = None,
    ) -> AgentRun:
        await self.check_cancelled(run=run, journal=journal, lock=True)
        await self._merge_journal(run, journal)
        run.checkpoint = {**(run.checkpoint or {}), "node": node, "details": details or {}}
        run.version += 1
        await self.repository.commit()
        return run

    async def check_cancelled(
        self,
        *,
        run: AgentRun,
        journal: dict | None = None,
        lock: bool = False,
    ) -> AgentRun:
        """Refresh a running Agent run and stop execution when cancellation was requested."""
        if lock:
            await self.repository.refresh_locked(run)
        else:
            await self.repository.refresh(run)
            if run.status == "cancel_requested":
                await self.repository.refresh_locked(run)
        if run.status == "cancel_requested":
            await self._merge_journal(run, journal)
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            run.version += 1
            await self.repository.commit()
            raise AgentRunCancelledError("Agent run was cancelled")
        if run.status != "running":
            # A timed-out or superseded worker must not commit late tool writes
            # or turn an already terminated run into a successful one.
            await self.repository.rollback()
            await self.repository.refresh(run)
            raise AgentRunCancelledError("本次处理已结束，未执行新的操作，请核对已有草稿。")
        return run

    async def abort(self, *, run: AgentRun, reason: str, journal: dict | None = None) -> AgentRun:
        """Close a non-terminal run when its stream consumer disappears."""
        await self.repository.refresh_locked(run)
        if run.status in {"succeeded", "failed", "cancelled"}:
            await self.repository.rollback()
            await self.repository.refresh(run)
            return run
        await self._merge_journal(run, journal)
        run.status = "cancelled"
        run.error_code = "AGENT_STREAM_CLOSED"
        run.error_message = reason[:500]
        run.checkpoint = {
            **(run.checkpoint or {}),
            "node": "stream_closed",
            "details": {"reason": reason[:200]},
        }
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def succeed(
        self,
        *,
        run: AgentRun,
        result_payload: dict,
        journal: dict | None = None,
    ) -> AgentRun:
        await self.check_cancelled(run=run, journal=journal, lock=True)
        await self._merge_journal(run, journal)
        run.status = "succeeded"
        run.result_payload = result_payload
        run.checkpoint = {**(run.checkpoint or {}), "node": "completed"}
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def fail(
        self,
        *,
        run: AgentRun,
        error_code: str,
        error_message: str,
        journal: dict | None = None,
    ) -> AgentRun:
        # Preserve a failed branch response assigned by the workflow before the
        # refresh, while fencing workers whose run was closed by another turn.
        result_payload = deepcopy(run.result_payload)
        await self.repository.refresh_locked(run)
        if run.status in {"succeeded", "failed", "cancelled"}:
            await self.repository.rollback()
            await self.repository.refresh(run)
            return run
        await self._merge_journal(run, journal)
        if result_payload is not None:
            run.result_payload = result_payload
        run.status = "failed"
        run.error_code = error_code
        run.error_message = error_message[:2000]
        run.checkpoint = {**(run.checkpoint or {}), "node": "failed"}
        run.finished_at = datetime.now(UTC)
        run.version += 1
        await self.repository.commit()
        return run

    async def _merge_journal(self, run: AgentRun, journal: dict | None) -> None:
        if not journal:
            return
        checkpoint = dict(run.checkpoint or {})
        refs: list[UUID] = []
        old_refs = checkpoint.get("confirmation_refs", [])
        new_refs = journal.get("confirmation_refs", [])
        for value in [
            *(old_refs if isinstance(old_refs, list) else []),
            *(new_refs if isinstance(new_refs, list) else []),
        ]:
            try:
                ref = UUID(str(value))
            except (ValueError, TypeError, AttributeError):
                continue
            if ref not in refs:
                refs.append(ref)
        # Flush/autoflush and this existence check use the same transaction as
        # the proposals. Rolled-back or foreign proposals are never recoverable.
        if refs:
            existing = await self.repository.existing_confirmation_refs(run.user_id, refs)
            checkpoint["confirmation_refs"] = [str(ref) for ref in refs if ref in existing]
        for field in ("tool_runs", "operations", "unknown_operations"):
            values = journal.get(field)
            if isinstance(values, list):
                allowed = {
                    "tool_name",
                    "status",
                    "duration_ms",
                    "error_code",
                    "tool_call_id",
                    "argument_fingerprint",
                    "replayed",
                    "confirmation_id",
                    "resource_id",
                    "conversation_id",
                    "turn_id",
                    "task_id",
                    "trace_id",
                    "tool_call_id_source",
                }
                checkpoint[field] = [
                    {
                        key: value[:255] if isinstance(value, str) else value
                        for key, value in item.items()
                        if key in allowed and isinstance(value, (str, int, float, bool))
                    }
                    for item in values[-100:]
                    if isinstance(item, dict)
                ]
                if field == "tool_runs":
                    from nxtrep_backend.agents.tools.registry import safe_trace_snapshot

                    for saved, original in zip(
                        checkpoint[field],
                        [item for item in values[-100:] if isinstance(item, dict)],
                        strict=True,
                    ):
                        for name in ("arguments_snapshot", "result_snapshot"):
                            if name in original:
                                saved[name] = safe_trace_snapshot(original[name])
        if isinstance(journal.get("task_state"), dict):
            from nxtrep_backend.schemas.agent_task import bounded_data
            from nxtrep_backend.services.agent_task_state import TaskStateManager

            new_state = TaskStateManager.load(journal["task_state"]).model_dump(mode="json")
            previous = checkpoint.get("task_state", {})
            if previous != new_state:

                def focus(raw):
                    active = raw.get("active_task") or {}
                    return {
                        key: active.get(key)
                        for key in (
                            "task_id",
                            "task_type",
                            "status",
                            "current_step",
                            "entities",
                            "parameters",
                            "missing_fields",
                        )
                    }

                checkpoint["state_changes"] = [
                    *checkpoint.get("state_changes", []),
                    {"from": bounded_data(focus(previous)), "to": bounded_data(focus(new_state))},
                ][-20:]
            checkpoint["task_state"] = new_state
        if isinstance(journal.get("action_plan"), dict):
            from nxtrep_backend.schemas.agent import AgentIntentPlan

            checkpoint["action_plan"] = AgentIntentPlan.model_validate(
                journal["action_plan"]
            ).model_dump(mode="json")
        run.checkpoint = checkpoint

    async def rollback_pending(self, *, run: AgentRun) -> None:
        """Discard unfinished tool writes before persisting a workflow timeout."""
        await self.repository.session.rollback()
        await self.repository.refresh(run)

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
