from collections.abc import AsyncIterator
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
from nxtrep_backend.services.agent_monitoring import AgentRunMonitor
from nxtrep_backend.services.agent_run import (
    AgentRunCancelledError,
    AgentRunService,
)
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
    ) -> None:
        self._graph = graph
        self._conversation_service = conversation_service
        self._run_service = run_service
        self._cancel_poll_interval_seconds = max(cancel_poll_interval_seconds, 0.0)
        self._monitor = monitor or AgentRunMonitor()

    async def chat(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
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
            await self._run_service.checkpoint(run=run, node="executing_graph")
        try:
            result = await self._graph.ainvoke(
                {
                    "user_id": user_id,
                    "request": effective_request,
                    "conversation_context": conversation_context,
                }
            )
            if run is not None and self._run_service is not None:
                await self._run_service.checkpoint(run=run, node="graph_completed")
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
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
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
        try:
            if self._run_service is not None:
                run = await self._run_service.start(
                    user_id=user_id,
                    conversation_id=conversation.id,
                    request_payload=effective_request.model_dump(mode="json"),
                )
                self._monitor.run_started(run_id=run.id, conversation_id=conversation.id)
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
            async for mode, data in self._graph.astream(
                accumulated,
                stream_mode=["updates", "custom"],
            ):
                if (
                    run is not None
                    and self._run_service is not None
                    and monotonic() >= next_cancel_check
                ):
                    await self._run_service.check_cancelled(run=run)
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
                for node, values in data.items():
                    if isinstance(values, dict):
                        accumulated.update(values)
                    if run is not None and self._run_service is not None:
                        await self._run_service.checkpoint(run=run, node=node)
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
            await self._record_failure(run, exc)
            if run is not None:
                self._monitor.run_failed(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    error_code=type(exc).__name__,
                )
            yield AgentStreamEvent(
                event="failed",
                run_id=run.id if run is not None else None,
                error_code=type(exc).__name__,
                message="Agent execution failed",
            )
        finally:
            if (
                run is not None
                and self._run_service is not None
                and run.status not in {"succeeded", "failed", "cancelled"}
            ):
                await self._run_service.abort(run=run, reason="Agent stream consumer disconnected")
                self._monitor.run_cancelled(
                    run_id=run.id,
                    duration_ms=self._elapsed_ms(workflow_started),
                    reason="stream_disconnected",
                )

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
        await self._conversation_service.finish_turn(
            conversation=conversation,
            assistant_message=normalized_response,
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
                )
            else:
                await self._run_service.succeed(
                    run=run,
                    result_payload=response.model_dump(mode="json"),
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

    async def _record_failure(self, run: AgentRun | None, exc: Exception) -> None:
        if (
            run is not None
            and self._run_service is not None
            and run.status not in {"failed", "cancelled", "succeeded"}
        ):
            await self._run_service.fail(
                run=run,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
