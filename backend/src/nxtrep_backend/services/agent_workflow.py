import asyncio
from collections.abc import AsyncIterator, Callable
from time import monotonic
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph

from nxtrep_backend.db.models import AgentConversation, AgentRun
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentExecutionBundle,
    AgentStreamEvent,
)
from nxtrep_backend.services.agent_errors import public_agent_error
from nxtrep_backend.services.agent_monitoring import AgentRunMonitor
from nxtrep_backend.services.agent_run import (
    AgentRunCancelledError,
    AgentRunService,
)
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.agent_turn import AgentTurnDecision, AgentTurnService
from nxtrep_backend.services.conversation import ConversationService


class AgentWorkflowResultError(RuntimeError):
    pass


class AgentWorkflowService:
    def __init__(
        self,
        graph: CompiledStateGraph,
        conversation_service: ConversationService,
        run_service: AgentRunService | None = None,
        cancel_poll_interval_seconds: float = 0.5,
        monitor: AgentRunMonitor | None = None,
        timeout_seconds: float = 120,
        tool_journal_provider: Callable[[], dict] | None = None,
        turn_service: AgentTurnService | None = None,
        trace_context: dict | None = None,
    ) -> None:
        self._graph = graph
        self._conversation_service = conversation_service
        self._run_service = run_service
        self._cancel_poll_interval_seconds = max(cancel_poll_interval_seconds, 0.0)
        self._monitor = monitor or AgentRunMonitor()
        self._timeout_seconds = timeout_seconds
        self._tool_journal_provider = tool_journal_provider
        self._turn_service = turn_service
        self._trace_context = trace_context

    async def chat(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
    ) -> AgentChatResponse:
        decision = (
            await self._turn_service.begin(user_id=user_id, request=request)
            if self._turn_service
            else None
        )
        if decision is not None and decision.response is not None:
            return decision.response
        try:
            response = await self._chat_new_turn(
                user_id=user_id, request=request, decision=decision
            )
            if self._turn_service is not None and decision is not None:
                await self._turn_service.complete(decision=decision, response=response)
            return response
        except Exception as exc:
            if self._turn_service is not None and decision is not None:
                await self._turn_service.fail(
                    decision=decision, error_code=public_agent_error(exc).code
                )
            raise

    async def _chat_new_turn(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
        decision: AgentTurnDecision | None = None,
    ) -> AgentChatResponse:
        conversation, conversation_context = await self._conversation_service.begin_turn(
            user_id=user_id,
            conversation_id=request.conversation_id,
            user_message=request.message,
            image_asset_ids=request.image_asset_ids,
        )
        effective_request = request.model_copy(update={"conversation_id": conversation.id})
        run: AgentRun | None = None
        workflow_started = monotonic()
        if self._run_service is not None:
            run = await self._run_service.start(
                user_id=user_id,
                conversation_id=conversation.id,
                request_payload=effective_request.model_dump(mode="json"),
            )
            self._monitor.run_started(run_id=run.id, conversation_id=conversation.id)
            await self._attach_turn(decision, run)
            await self._run_service.checkpoint(run=run, node="executing_graph")
        try:
            result = await asyncio.wait_for(
                self._graph.ainvoke(
                    {
                        "user_id": user_id,
                        "request": effective_request,
                        "conversation_context": conversation_context,
                    }
                ),
                timeout=self._timeout_seconds,
            )
            if run is not None and self._run_service is not None:
                await self._run_service.checkpoint(
                    run=run,
                    node="graph_completed",
                    **self._journal_kwargs(result),
                )
            response = await self._finish_response(
                conversation=conversation,
                result=result,
                run=run,
            )
            if run is not None:
                self._monitor_response(
                    run=run,
                    response=response,
                    duration_ms=self._elapsed_ms(workflow_started),
                )
            return response
        except AgentRunCancelledError:
            if run is not None:
                self._monitor.run_cancelled(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    reason="cancel_requested",
                )
            raise
        except Exception as exc:
            await self._record_failure(run, exc)
            if run is not None:
                self._monitor.run_failed(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    error_code=type(exc).__name__,
                )
            raise

    async def stream(
        self, *, user_id: UUID, request: AgentChatRequest
    ) -> AsyncIterator[AgentStreamEvent]:
        decision = None
        finished = False
        inner = None
        try:
            decision = (
                await self._turn_service.begin(user_id=user_id, request=request)
                if self._turn_service
                else None
            )
            if decision is not None and decision.response is not None:
                response = decision.response
                yield AgentStreamEvent(event="run_started", run_id=response.run_id)
                yield AgentStreamEvent(
                    event="message_delta",
                    run_id=response.run_id,
                    delta=response.message,
                    sequence=1,
                    node="synthesize_response",
                )
                yield AgentStreamEvent(event="completed", run_id=response.run_id, response=response)
                finished = True
                return
            inner = self._stream_new_turn(user_id=user_id, request=request, decision=decision)
            async for event in inner:
                if event.event == "completed":
                    if self._turn_service is not None and decision is not None:
                        await self._turn_service.complete(
                            decision=decision, response=event.response
                        )
                    finished = True
                elif event.event in {"failed", "cancelled"}:
                    if self._turn_service is not None and decision is not None:
                        await self._turn_service.fail(
                            decision=decision,
                            error_code=event.error_code or "AGENT_TURN_INTERRUPTED",
                        )
                    finished = True
                yield event
        except Exception as exc:
            error = public_agent_error(exc)
            if self._turn_service is not None and decision is not None and not finished:
                await self._turn_service.fail(decision=decision, error_code=error.code)
                finished = True
            yield AgentStreamEvent(
                event="failed",
                run_id=getattr(exc, "run_id", None),
                error_code=error.code,
                message=error.message,
            )
        finally:
            if inner is not None:
                await inner.aclose()
            if self._turn_service is not None and decision is not None and not finished:
                await self._turn_service.fail(decision=decision)

    async def _attach_turn(self, decision, run):
        if self._turn_service is not None and decision is not None:
            await self._turn_service.attach_run(decision=decision, run=run)
        if self._trace_context is not None:
            self._trace_context.update(
                conversation_id=str(run.conversation_id),
                turn_id=str(decision.client_turn_id)
                if decision and decision.client_turn_id
                else str(run.id),
                trace_id=str(run.id),
            )

    async def _stream_new_turn(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
        decision: AgentTurnDecision | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        conversation, conversation_context = await self._conversation_service.begin_turn(
            user_id=user_id,
            conversation_id=request.conversation_id,
            user_message=request.message,
            image_asset_ids=request.image_asset_ids,
        )
        effective_request = request.model_copy(update={"conversation_id": conversation.id})
        run: AgentRun | None = None
        workflow_started = monotonic()
        previous_node_completed = workflow_started
        accumulated: dict = {}
        try:
            if self._run_service is not None:
                run = await self._run_service.start(
                    user_id=user_id,
                    conversation_id=conversation.id,
                    request_payload=effective_request.model_dump(mode="json"),
                )
                self._monitor.run_started(run_id=run.id, conversation_id=conversation.id)
                await self._attach_turn(decision, run)
            yield AgentStreamEvent(
                event="run_started",
                run_id=run.id if run is not None else None,
            )
            accumulated: dict = {
                "user_id": user_id,
                "request": effective_request,
                "conversation_context": conversation_context,
                "streaming": True,
            }
            message_sequence = 0
            streamed_response_parts: list[str] = []
            next_cancel_check = monotonic()
            async for mode, data in self._bounded_graph_events(accumulated):
                # The node has already executed. Capture its proposal references
                # before acknowledging cancellation at this boundary, including
                # dedicated image handlers which do not use the tool gateway.
                if mode == "updates" and isinstance(data, dict):
                    for values in data.values():
                        if isinstance(values, dict):
                            accumulated.update(values)
                if (
                    run is not None
                    and self._run_service is not None
                    and monotonic() >= next_cancel_check
                ):
                    await self._run_service.check_cancelled(
                        run=run,
                        **self._journal_kwargs(accumulated),
                    )
                    next_cancel_check = monotonic() + self._cancel_poll_interval_seconds
                if mode == "custom":
                    if not isinstance(data, dict):
                        continue
                    if data.get("event") != "message_delta":
                        continue
                    if data.get("node") != "synthesize_response":
                        continue
                    delta = data.get("delta")
                    if not isinstance(delta, str) or not delta:
                        continue
                    message_sequence += 1
                    streamed_response_parts.append(delta)
                    yield AgentStreamEvent(
                        event="message_delta",
                        run_id=run.id if run is not None else None,
                        node="synthesize_response",
                        delta=delta,
                        sequence=message_sequence,
                    )
                    continue
                if mode != "updates" or not isinstance(data, dict):
                    continue
                for node in data:
                    if run is not None and self._run_service is not None:
                        await self._run_service.checkpoint(
                            run=run,
                            node=node,
                            **self._journal_kwargs(accumulated),
                        )
                        node_completed = monotonic()
                        self._monitor.node_completed(
                            run_id=run.id,
                            node=node,
                            total_elapsed_ms=self._elapsed_ms(workflow_started, node_completed),
                            node_elapsed_ms=self._elapsed_ms(
                                previous_node_completed,
                                node_completed,
                            ),
                        )
                        previous_node_completed = node_completed
                    yield AgentStreamEvent(
                        event="node_completed",
                        run_id=run.id if run is not None else None,
                        node=node,
                    )
            response_message = accumulated.get("response_message")
            if not isinstance(response_message, str) or (
                "".join(streamed_response_parts).strip() != response_message.strip()
            ):
                raise AgentWorkflowResultError(
                    "Agent stream deltas do not match the final response message"
                )
            response = await self._finish_response(
                conversation=conversation,
                result=accumulated,
                run=run,
            )
            if run is not None:
                self._monitor_response(
                    run=run,
                    response=response,
                    duration_ms=self._elapsed_ms(workflow_started),
                )
            yield AgentStreamEvent(
                event="completed",
                run_id=run.id if run is not None else None,
                response=response,
            )
        except AgentRunCancelledError as exc:
            if run is not None:
                self._monitor.run_cancelled(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    reason="cancel_requested",
                )
            yield AgentStreamEvent(
                event="cancelled",
                run_id=run.id if run is not None else None,
                error_code="AGENT_RUN_CANCELLED",
                message=str(exc),
            )
        except Exception as exc:
            await self._record_failure(run, exc, result=accumulated)
            if run is not None:
                self._monitor.run_failed(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    error_code=type(exc).__name__,
                )
            public_error = public_agent_error(exc)
            yield AgentStreamEvent(
                event="failed",
                run_id=run.id if run is not None else None,
                error_code=(
                    public_error.code
                    if public_error.code != "BRANCH_EXECUTION_FAILED"
                    else type(exc).__name__
                ),
                message=public_error.message,
            )
        finally:
            if (
                run is not None
                and self._run_service is not None
                and run.status not in {"succeeded", "failed", "cancelled"}
            ):
                await self._run_service.abort(
                    run=run,
                    reason="Agent stream consumer disconnected",
                    **self._journal_kwargs(accumulated),
                )
                self._monitor.run_cancelled(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    reason="stream_disconnected",
                )

    async def _bounded_graph_events(self, state: dict) -> AsyncIterator:
        stream = self._graph.astream(state, stream_mode=["updates", "custom"])
        deadline = monotonic() + self._timeout_seconds
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        anext(stream),
                        timeout=max(0, deadline - monotonic()),
                    )
                except StopAsyncIteration:
                    return
                yield event
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    @staticmethod
    def _elapsed_ms(started: float, finished: float | None = None) -> int:
        return max(0, round(((finished if finished is not None else monotonic()) - started) * 1000))

    async def _finish_response(
        self,
        *,
        conversation: AgentConversation,
        result: dict,
        run: AgentRun | None,
    ) -> AgentChatResponse:
        response_message = result.get("response_message")
        if not isinstance(response_message, str) or not response_message.strip():
            raise AgentWorkflowResultError("Agent graph returned no response message")
        execution_bundle = result.get("execution_bundle")
        if not isinstance(execution_bundle, AgentExecutionBundle):
            raise AgentWorkflowResultError("Agent graph returned no execution bundle")
        normalized_response = response_message.strip()
        context = result.get("conversation_context")
        state_kwargs = {}
        if context is not None and isinstance(getattr(context, "task_state", None), dict):
            if context.task_state.get("active_task") or context.task_state.get("suspended_task"):
                state_kwargs = {"task_state": context.task_state}
        await self._conversation_service.finish_turn(
            conversation=conversation,
            assistant_message=normalized_response,
            **state_kwargs,
        )
        branch_results = execution_bundle.branch_results
        confirmation_cards = list(
            {
                card.confirmation_id: card
                for branch in branch_results
                for card in branch.confirmation_cards
            }.values()
        )
        citations = list(
            {
                (item.source_type, item.source_id): item
                for branch in branch_results
                for item in branch.citations
            }.values()
        )
        statuses = {branch.status for branch in branch_results}
        if statuses == {"completed"}:
            response_status = "completed"
        elif statuses <= {"needs_input"}:
            response_status = "needs_input"
        elif statuses == {"failed"}:
            response_status = "failed"
        else:
            response_status = "partial"
        response = AgentChatResponse(
            message=normalized_response,
            conversation_id=conversation.id,
            run_id=run.id if run is not None else None,
            status=response_status,
            analysis_results=branch_results,
            confirmation_cards=confirmation_cards,
            citations=citations,
        )
        if run is not None and self._run_service is not None:
            if response_status == "failed":
                run.result_payload = response.model_dump(mode="json")
                first_error = next(
                    (branch.error for branch in branch_results if branch.error is not None),
                    None,
                )
                await self._run_service.fail(
                    run=run,
                    error_code=(first_error.code if first_error else "AGENT_RESPONSE_FAILED"),
                    error_message=(
                        first_error.message if first_error else "Every Agent branch failed"
                    ),
                    **self._journal_kwargs(result),
                )
            else:
                await self._run_service.succeed(
                    run=run,
                    result_payload=response.model_dump(mode="json"),
                    **self._journal_kwargs(result),
                )
        return response

    def _monitor_response(
        self,
        *,
        run: AgentRun,
        response: AgentChatResponse,
        duration_ms: int,
    ) -> None:
        if response.status == "failed":
            self._monitor.run_failed(
                run_id=run.id,
                duration_ms=duration_ms,
                error_code=self._response_error_code(response),
            )
            return
        self._monitor.run_succeeded(
            run_id=run.id,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _response_error_code(response: AgentChatResponse) -> str:
        return next(
            (branch.error.code for branch in response.analysis_results if branch.error is not None),
            "AGENT_RESPONSE_FAILED",
        )

    def _journal_kwargs(self, result: dict | None = None) -> dict:
        journal = (
            dict(self._tool_journal_provider()) if self._tool_journal_provider is not None else {}
        )
        bundle = (result or {}).get("execution_bundle")
        context = (result or {}).get("conversation_context")
        planned = (result or {}).get("planned_request")
        if planned is not None:
            journal["action_plan"] = planned.intent_plan.model_dump(mode="json")
        if context is not None and isinstance(getattr(context, "task_state", None), dict):
            journal["task_state"] = TaskStateManager.load(context.task_state).model_dump(
                mode="json"
            )
        refs = list(journal.get("confirmation_refs", []))
        if isinstance(bundle, AgentExecutionBundle):
            refs.extend(
                str(card.confirmation_id)
                for branch in bundle.branch_results
                for card in branch.confirmation_cards
            )
        if refs:
            journal["confirmation_refs"] = list(dict.fromkeys(refs))
        return {"journal": journal} if journal else {}

    async def _record_failure(
        self,
        run: AgentRun | None,
        exc: Exception,
        *,
        result: dict | None = None,
    ) -> None:
        if (
            run is not None
            and self._run_service is not None
            and run.status not in {"failed", "cancelled", "succeeded"}
        ):
            error = public_agent_error(exc)
            if error.code in {"AGENT_TIMEOUT", "DATA_ACCESS_FAILED"}:
                await self._run_service.rollback_pending(run=run)
            await self._run_service.fail(
                run=run,
                error_code=(
                    error.code if error.code != "BRANCH_EXECUTION_FAILED" else type(exc).__name__
                ),
                error_message=error.message,
                **self._journal_kwargs(result),
            )
