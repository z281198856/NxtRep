"""Stable client turn identity; replays results without rerunning an Agent action."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from nxtrep_backend.db.models import AgentRun, IdempotencyRecord
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.idempotency import SqlAlchemyIdempotencyRepository
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentChatResponse
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.idempotency import (
    IdempotencyDecision,
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
    IdempotencyService,
)

OPERATION = "agent_chat_turn"


@dataclass(frozen=True, slots=True)
class AgentTurnDecision:
    user_id: UUID
    client_turn_id: UUID | None
    request_hash: str
    record_id: UUID | None = None
    replayed: bool = False
    replay_run: AgentRun | None = None
    response: AgentChatResponse | None = None


class AgentTurnReplayError(RuntimeError):
    """A prior turn ended without a reusable response; its action must not run again."""

    def __init__(self, error_code: str, message: str, run_id: UUID | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.run_id = run_id
        self.status_code = 409


class AgentTurnInProgressError(IdempotencyRequestInProgressError):
    def __init__(self, message: str, run_id: UUID | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.error_code = "AGENT_TURN_IN_PROGRESS" if run_id else "AGENT_TURN_STARTING"
        self.status_code = 409


class AgentTurnService:
    def __init__(
        self,
        idempotency_repository: SqlAlchemyIdempotencyRepository,
        run_repository: SqlAlchemyAgentRunRepository,
        *,
        startup_timeout_seconds: float = 180,
        stale_after_seconds: float = 600,
        workflow_timeout_seconds: float = 120,
    ) -> None:
        self.idempotency = IdempotencyService(idempotency_repository)
        self.runs = run_repository
        self.session = run_repository.session
        self.startup_timeout = timedelta(seconds=max(startup_timeout_seconds, 1))
        if stale_after_seconds < workflow_timeout_seconds + 300:
            raise ValueError("stale_after_seconds must exceed the workflow timeout by 300 seconds")
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.run_service = AgentRunService(run_repository, stale_after_seconds=stale_after_seconds)

    @staticmethod
    def _payload(request: AgentChatRequest) -> dict:
        return request.model_dump(mode="json", exclude={"client_turn_id"})

    async def begin(self, *, user_id: UUID, request: AgentChatRequest) -> AgentTurnDecision:
        payload = self._payload(request)
        request_hash = IdempotencyService._hash_payload(payload)
        key = request.client_turn_id
        if key is None:
            return AgentTurnDecision(
                user_id=user_id, client_turn_id=None, request_hash=request_hash
            )
        try:
            existing = await self.session.scalar(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.idempotency_key == key,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            run = await self.runs.get_owned_by_client_turn(user_id=user_id, client_turn_id=key)
            if existing is not None:
                if existing.operation != OPERATION or existing.request_hash != request_hash:
                    raise IdempotencyKeyConflictError(
                        "同一个请求标识不能用于不同内容，请发送新的请求。"
                    )
                decision = AgentTurnDecision(
                    user_id=user_id,
                    client_turn_id=key,
                    request_hash=request_hash,
                    record_id=existing.id,
                    replayed=True,
                    replay_run=run,
                )
                if run is not None:
                    self._check_run_hash(
                        run, request, request_hash, trusted_hash=existing.request_hash
                    )
                    await self._recover_stale_run(run)
                    response = self._response_from_run(run)
                    # Recover a crash between AgentRun completion and response-cache completion.
                    if existing.status == "processing":
                        await self._cache(decision, response=response, run=run)
                    await self.session.commit()
                    return AgentTurnDecision(
                        user_id=user_id,
                        client_turn_id=key,
                        request_hash=request_hash,
                        record_id=existing.id,
                        replayed=True,
                        replay_run=run,
                        response=response,
                    )
                if existing.status == "completed":
                    response = self._response_from_cache(existing.response_body)
                    await self.session.commit()
                    return AgentTurnDecision(
                        user_id=user_id,
                        client_turn_id=key,
                        request_hash=request_hash,
                        record_id=existing.id,
                        replayed=True,
                        response=response,
                    )
                # Processing with no attached run is an uncertain startup, never a new action.
                if datetime.now(UTC) - existing.created_at > self.startup_timeout:
                    raise AgentTurnReplayError(
                        "AGENT_TURN_NOT_STARTED",
                        "上次请求在启动时中断，暂未找到可恢复的运行；不会重复执行。请核对草稿后发送新的请求。",
                    )
                raise AgentTurnInProgressError("这条请求正在启动，请稍后恢复结果；不要重复发送。")
            if run is not None:
                self._check_run_hash(run, request, request_hash)
                await self._recover_stale_run(run)
                response = self._response_from_run(run)
                await self.session.commit()
                return AgentTurnDecision(
                    user_id=user_id,
                    client_turn_id=key,
                    request_hash=request_hash,
                    replayed=True,
                    replay_run=run,
                    response=response,
                )
            try:
                acquired = await self.idempotency.begin(
                    user_id=user_id, idempotency_key=key, operation=OPERATION, payload=payload
                )
            except IdempotencyRequestInProgressError:
                # The generic repository's unique user/key claim fences concurrent first requests.
                raise AgentTurnInProgressError(
                    "这条请求正在启动，请稍后恢复结果；不要重复发送。"
                ) from None
            if acquired.replayed:
                response = self._response_from_cache(acquired.response_body)
                await self.session.commit()
                return AgentTurnDecision(
                    user_id=user_id,
                    client_turn_id=key,
                    request_hash=request_hash,
                    record_id=acquired.record_id,
                    replayed=True,
                    response=response,
                )
            await self.session.commit()
            return AgentTurnDecision(
                user_id=user_id,
                client_turn_id=key,
                request_hash=request_hash,
                record_id=acquired.record_id,
            )
        except Exception:
            await self.session.rollback()
            raise

    async def _recover_stale_run(self, run: AgentRun) -> None:
        if run.status in {"running", "cancel_requested"} and (
            datetime.now(UTC) - run.started_at >= self.stale_after
        ):
            # Reuse the same locked transition and worker fence as normal failures.
            # This closes a crashed run, preserving its journal; it never restarts it.
            await self.run_service.fail(
                run=run,
                error_code="AGENT_RUN_INTERRUPTED",
                error_message="上次请求已中断，不会重复执行。请核对已生成的草稿或记录后继续。",
            )

    @staticmethod
    def _check_run_hash(
        run: AgentRun, request: AgentChatRequest, request_hash: str, trusted_hash: str | None = None
    ) -> None:
        stored_hash = (run.checkpoint or {}).get("client_request_hash")
        if stored_hash is None and trusted_hash is not None:
            stored_hash = trusted_hash
        if stored_hash is None:
            # Compatibility for a turn written before attach_run was reached.
            payload = dict(run.request_payload or {})
            payload.pop("client_turn_id", None)
            if request.conversation_id is None:
                payload["conversation_id"] = None
            stored_hash = IdempotencyService._hash_payload(payload)
        if stored_hash != request_hash:
            raise IdempotencyKeyConflictError("同一个请求标识不能用于不同内容，请发送新的请求。")

    @staticmethod
    def _response_from_run(run: AgentRun) -> AgentChatResponse:
        if run.status in {"running", "cancel_requested"}:
            raise AgentTurnInProgressError(
                "这条请求仍在处理，请稍后恢复结果；不要重复执行。", run.id
            )
        if run.result_payload is not None:
            try:
                response = AgentChatResponse.model_validate(run.result_payload)
                if response.conversation_id != run.conversation_id or response.run_id != run.id:
                    raise AgentTurnReplayError(
                        "AGENT_RESULT_INVALID",
                        "上次回复与运行记录不一致，请核对已有草稿或记录后发送新的请求。",
                        run.id,
                    )
                return response
            except ValidationError:
                raise AgentTurnReplayError(
                    "AGENT_RESULT_INVALID",
                    "上次返回内容不完整，请核对已有草稿或记录后发送新的请求。",
                    run.id,
                ) from None
        code = "AGENT_TURN_CANCELLED" if run.status == "cancelled" else "AGENT_TURN_INTERRUPTED"
        raise AgentTurnReplayError(
            code,
            "这条请求已取消或中断，不会重复执行。请核对已有草稿或记录，再发送新的请求。",
            run.id,
        )

    @staticmethod
    def _response_from_cache(body) -> AgentChatResponse:
        if isinstance(body, dict) and body.get("response") is not None:
            try:
                return AgentChatResponse.model_validate(body["response"])
            except ValidationError:
                pass
        if isinstance(body, dict) and body.get("error_code"):
            raise AgentTurnReplayError(
                str(body["error_code"]),
                "这条请求已取消或中断，不会重复执行。请核对已有草稿或记录，再发送新的请求。",
                UUID(body["run_id"]) if body.get("run_id") else None,
            )
        raise AgentTurnReplayError(
            "AGENT_RESULT_INVALID",
            "上次请求没有可恢复的完整回复，请核对已有草稿或记录后发送新的请求。",
        )

    async def attach_run(self, *, decision: AgentTurnDecision, run: AgentRun) -> None:
        if decision.client_turn_id is None or decision.replayed:
            return
        if run.user_id != decision.user_id:
            raise ValueError("Cannot attach another user's run")
        run.checkpoint = {
            **(run.checkpoint or {}),
            "client_turn_id": str(decision.client_turn_id),
            "client_request_hash": decision.request_hash,
        }
        await self.session.commit()

    async def _cache(self, decision, *, response=None, run=None, error_code=None) -> None:
        if decision.record_id is None:
            return
        if run is not None and run.user_id != decision.user_id:
            raise ValueError("Cannot cache another user's run")
        current = await self.session.scalar(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == decision.record_id,
                IdempotencyRecord.user_id == decision.user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current is None
            or current.operation != OPERATION
            or current.request_hash != decision.request_hash
        ):
            raise IdempotencyKeyConflictError("请求标识状态已变化，不能覆盖原请求结果。")
        if current.status == "completed":
            # A reconnect may have recovered the durable result before the original
            # HTTP handler reaches this point. The first completed response is stable.
            return
        body = (
            {"response": response.model_dump(mode="json")}
            if response is not None
            else {
                "error_code": error_code or "AGENT_TURN_INTERRUPTED",
                "run_id": str(run.id) if run else None,
            }
        )
        await self.idempotency.complete(
            decision=IdempotencyDecision(
                record_id=decision.record_id,
                replayed=False,
                response_status=None,
                response_body=None,
            ),
            response_status=200 if response is not None else 409,
            response_body=body,
        )

    async def complete(
        self,
        *,
        decision: AgentTurnDecision,
        response: AgentChatResponse | None = None,
        run: AgentRun | None = None,
    ) -> None:
        if decision.client_turn_id is None or decision.replayed:
            return
        if run is not None and run.status in {"running", "cancel_requested"}:
            raise ValueError("Cannot complete a running turn")
        if (
            run is not None
            and response is not None
            and (response.conversation_id != run.conversation_id or response.run_id != run.id)
        ):
            raise AgentTurnReplayError(
                "AGENT_RESULT_INVALID", "回复与当前运行不一致，结果未缓存，请核对已有草稿。", run.id
            )
        if response is None and run is not None:
            response = self._response_from_run(run)
        await self._cache(decision, response=response, run=run)
        await self.session.commit()

    async def fail(
        self,
        *,
        decision: AgentTurnDecision,
        run: AgentRun | None = None,
        error_code: str = "AGENT_TURN_INTERRUPTED",
        error_message: str = "",
    ) -> None:
        if decision.client_turn_id is None or decision.replayed:
            return
        response = None
        if run is not None:
            try:
                response = self._response_from_run(run)
            except AgentTurnReplayError:
                pass
        # Public response cache keeps only safe codes, never provider/SQL exception text.
        await self._cache(decision, response=response, run=run, error_code=error_code)
        await self.session.commit()
