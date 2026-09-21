import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from nxtrep_backend.agents.factory import (
    build_agent_workflow_service,
)
from nxtrep_backend.agents.intent_router import (
    AgentIntentRoutingError,
)
from nxtrep_backend.agents.synthesis import (
    AgentResponseSynthesisError,
)
from nxtrep_backend.api.deps import CurrentUserId, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.config import StorageConfigurationError, get_settings
from nxtrep_backend.providers.models import ModelConfigurationError
from nxtrep_backend.providers.storage import StorageProviderError
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentStreamEvent,
)
from nxtrep_backend.schemas.agent_run import (
    AgentRunCancelRequest,
    AgentRunResponse,
    AgentToolRunListResponse,
)
from nxtrep_backend.schemas.conversation import (
    AgentConversationCreateRequest,
    AgentConversationDeleteRequest,
    AgentConversationListResponse,
    AgentConversationMessageRequest,
    AgentConversationResponse,
    AgentConversationUpdateRequest,
    AgentMessageListResponse,
    AgentMessageResponse,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
)
from nxtrep_backend.services.agent_run import (
    AgentRunConflictError,
    AgentRunNotFoundError,
    AgentRunService,
)
from nxtrep_backend.services.agent_workflow import (
    AgentWorkflowResultError,
)
from nxtrep_backend.services.conversation import (
    AgentConversationConflictError,
    AgentConversationNotFoundError,
    ConversationService,
)

router = APIRouter()
logger = logging.getLogger(__name__)
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
SSE_DISCONNECT_POLL_INTERVAL_SECONDS = 1.0
SSE_HEARTBEAT = ": heartbeat\n\n"
SSE_OPENAPI_RESPONSE = {
    200: {
        "description": "Agent events encoded as a Server-Sent Events stream.",
        "content": {
            "text/event-stream": {
                "schema": {"type": "string"},
                "example": 'id: 1\\nevent: message_delta\\ndata: {"event":"message_delta"}\\n\\n',
            }
        },
    }
}


@router.get("/tool-runs", response_model=AgentToolRunListResponse)
async def list_tool_runs(
    user_id: CurrentUserId,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AgentToolRunListResponse:
    runs, total = await SqlAlchemyAgentRunRepository(session).list_owned(user_id, page, page_size)
    items = []
    for run in runs:
        tool_runs = run.checkpoint.get("tool_runs", [])
        for tool_run in tool_runs if isinstance(tool_runs, list) else []:
            if isinstance(tool_run, dict):
                items.append({"run_id": str(run.id), **tool_run})
    return AgentToolRunListResponse(
        list=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


def _encode_sse(event: AgentStreamEvent) -> str:
    event_id = f"id: {event.sequence}\n" if event.sequence is not None else ""
    return f"{event_id}event: {event.event}\ndata: {event.model_dump_json()}\n\n"


async def _stream_sse_events(
    *,
    events: AsyncIterator[AgentStreamEvent],
    is_disconnected: Callable[[], Awaitable[bool]],
    granularity: Literal["character", "chunk"],
    heartbeat_interval_seconds: float = SSE_HEARTBEAT_INTERVAL_SECONDS,
    disconnect_poll_interval_seconds: float = SSE_DISCONNECT_POLL_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Multiplex Agent events, transport heartbeats, and client disconnect checks."""
    character_sequence = 0
    pending_event: asyncio.Task[AgentStreamEvent] | None = None
    heartbeat_interval = max(heartbeat_interval_seconds, 0.0)
    disconnect_interval = max(disconnect_poll_interval_seconds, 0.0)
    next_heartbeat = monotonic() + heartbeat_interval

    try:
        while True:
            if await is_disconnected():
                return

            if pending_event is None:
                pending_event = asyncio.create_task(anext(events))

            now = monotonic()
            timeout = min(disconnect_interval, max(next_heartbeat - now, 0.0))
            done, _pending = await asyncio.wait({pending_event}, timeout=timeout)

            if not done:
                now = monotonic()
                if now >= next_heartbeat:
                    yield SSE_HEARTBEAT
                    next_heartbeat = now + heartbeat_interval
                continue

            completed_event = pending_event
            pending_event = None
            try:
                event = completed_event.result()
            except StopAsyncIteration:
                return

            next_heartbeat = monotonic() + heartbeat_interval
            if (
                event.event == "message_delta"
                and granularity == "character"
                and event.delta is not None
            ):
                for character in event.delta:
                    character_sequence += 1
                    yield _encode_sse(
                        event.model_copy(
                            update={
                                "delta": character,
                                "sequence": character_sequence,
                            }
                        )
                    )
                continue
            yield _encode_sse(event)
    finally:
        if pending_event is not None:
            pending_event.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending_event
        close = getattr(events, "aclose", None)
        if close is not None:
            await close()


def _conversation_service(session: DbSession) -> ConversationService:
    return ConversationService(SqlAlchemyConversationRepository(session))


def _run_service(session: DbSession) -> AgentRunService:
    return AgentRunService(SqlAlchemyAgentRunRepository(session))


def _raise_conversation_error(exc: RuntimeError) -> None:
    if isinstance(exc, AgentConversationNotFoundError):
        raise ApiError(
            status_code=404,
            code="AGENT_CONVERSATION_NOT_FOUND",
            message=str(exc),
        ) from exc
    if isinstance(exc, AgentConversationConflictError):
        raise ApiError(
            status_code=409,
            code="AGENT_CONVERSATION_CONFLICT",
            message=str(exc),
        ) from exc
    raise exc


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    body: AgentChatRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentChatResponse:
    try:
        service = build_agent_workflow_service(
            session=session,
            user_id=user_id,
        )

        return await service.chat(
            user_id=user_id,
            request=body,
        )

    except AgentImageAssetNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="IMAGE_ASSET_NOT_FOUND",
            message="Image asset not found",
        ) from exc

    except AgentConversationNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="AGENT_CONVERSATION_NOT_FOUND",
            message="Agent conversation not found",
        ) from exc

    except AgentImageAssetNotReadyError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="IMAGE_ASSET_NOT_READY",
            message="Image asset is not ready",
        ) from exc

    except StorageProviderError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc

    except (
        AgentIntentRoutingError,
        AgentResponseSynthesisError,
        AgentWorkflowResultError,
    ) as exc:
        raise ApiError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AGENT_INVALID_MODEL_RESPONSE",
            message="Agent model returned an invalid response",
        ) from exc

    except (
        ModelConfigurationError,
        StorageConfigurationError,
    ) as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AGENT_NOT_CONFIGURED",
            message=str(exc),
        ) from exc


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses=SSE_OPENAPI_RESPONSE,
)
async def stream_chat(
    body: AgentChatRequest,
    user_id: CurrentUserId,
    session: DbSession,
    request: Request,
    granularity: Literal["character", "chunk"] = Query(default="character"),
) -> StreamingResponse:
    try:
        service = build_agent_workflow_service(session=session, user_id=user_id)
    except (ModelConfigurationError, StorageConfigurationError) as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AGENT_NOT_CONFIGURED",
            message=str(exc),
        ) from exc

    async def event_source() -> AsyncIterator[str]:
        try:
            settings = get_settings()
            async for payload in _stream_sse_events(
                events=service.stream(user_id=user_id, request=body),
                is_disconnected=request.is_disconnected,
                granularity=granularity,
                heartbeat_interval_seconds=settings.agent_sse_heartbeat_seconds,
                disconnect_poll_interval_seconds=(settings.agent_sse_disconnect_poll_seconds),
            ):
                yield payload
        except Exception:
            logger.exception("Agent stream failed before execution started")
            yield _encode_sse(
                AgentStreamEvent(
                    event="failed",
                    error_code="AGENT_STREAM_FAILED",
                    message="Agent stream failed before execution started",
                )
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=AgentConversationListResponse)
async def list_conversations(
    user_id: CurrentUserId,
    session: DbSession,
    status_filter: Literal["active", "archived"] | None = Query(
        default=None,
        alias="status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AgentConversationListResponse:
    items, total = await _conversation_service(session).list_conversations(
        user_id=user_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return AgentConversationListResponse(
        list=[AgentConversationResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@router.post(
    "/conversations",
    response_model=AgentConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: AgentConversationCreateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentConversationResponse:
    item = await _conversation_service(session).create_conversation(
        user_id=user_id,
        title=body.title,
    )
    return AgentConversationResponse.model_validate(item)


@router.get(
    "/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
)
async def get_conversation(
    conversation_id: UUID,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentConversationResponse:
    try:
        item = await _conversation_service(session).get_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
    except RuntimeError as exc:
        _raise_conversation_error(exc)
    return AgentConversationResponse.model_validate(item)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
)
async def update_conversation(
    conversation_id: UUID,
    body: AgentConversationUpdateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentConversationResponse:
    try:
        item = await _conversation_service(session).update_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            expected_version=body.expected_version,
            title=body.title,
            status=body.status,
        )
    except RuntimeError as exc:
        _raise_conversation_error(exc)
    return AgentConversationResponse.model_validate(item)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: UUID,
    body: AgentConversationDeleteRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> Response:
    try:
        await _conversation_service(session).delete_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            expected_version=body.expected_version,
        )
    except RuntimeError as exc:
        _raise_conversation_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=AgentMessageListResponse,
)
async def list_conversation_messages(
    conversation_id: UUID,
    user_id: CurrentUserId,
    session: DbSession,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AgentMessageListResponse:
    try:
        items = await _conversation_service(session).list_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            after_sequence=after_sequence,
            limit=limit + 1,
        )
    except RuntimeError as exc:
        _raise_conversation_error(exc)
    has_more = len(items) > limit
    selected = items[:limit]
    return AgentMessageListResponse(
        list=[AgentMessageResponse.model_validate(item) for item in selected],
        next_sequence=selected[-1].sequence if has_more and selected else None,
        has_more=has_more,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses=SSE_OPENAPI_RESPONSE,
)
async def create_conversation_message(
    conversation_id: UUID,
    body: AgentConversationMessageRequest,
    user_id: CurrentUserId,
    session: DbSession,
    request: Request,
    granularity: Literal["character", "chunk"] = Query(default="character"),
) -> StreamingResponse:
    try:
        await _conversation_service(session).get_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
        )
    except RuntimeError as exc:
        _raise_conversation_error(exc)

    return await stream_chat(
        body=AgentChatRequest(
            message=body.message,
            conversation_id=conversation_id,
            image_asset_ids=body.image_asset_ids,
            context_hints=body.context_hints,
        ),
        user_id=user_id,
        session=session,
        request=request,
        granularity=granularity,
    )


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: UUID,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentRunResponse:
    try:
        item = await _run_service(session).get(user_id=user_id, run_id=run_id)
    except AgentRunNotFoundError as exc:
        raise ApiError(status_code=404, code="AGENT_RUN_NOT_FOUND", message=str(exc)) from exc
    return AgentRunResponse.model_validate(item)


@router.post("/runs/{run_id}:cancel", response_model=AgentRunResponse)
async def cancel_agent_run(
    run_id: UUID,
    body: AgentRunCancelRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> AgentRunResponse:
    try:
        item = await _run_service(session).request_cancel(
            user_id=user_id,
            run_id=run_id,
            expected_version=body.expected_version,
        )
    except AgentRunNotFoundError as exc:
        raise ApiError(status_code=404, code="AGENT_RUN_NOT_FOUND", message=str(exc)) from exc
    except AgentRunConflictError as exc:
        raise ApiError(status_code=409, code="AGENT_RUN_CONFLICT", message=str(exc)) from exc
    return AgentRunResponse.model_validate(item)
