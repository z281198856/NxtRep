from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nxtrep_backend.api.deps import CurrentUserId, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
from nxtrep_backend.schemas.memory import (
    MemoryCreateRequest,
    MemoryDeleteRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
)
from nxtrep_backend.services.memory import (
    MemoryCategory,
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryService,
)

router = APIRouter()


def _service(session: DbSession) -> MemoryService:
    return MemoryService(SqlAlchemyMemoryRepository(session))


def _response(item) -> MemoryResponse:
    return MemoryResponse(
        id=item.id,
        category=item.category,
        content=item.content,
        source=item.source,
        saved_at=item.confirmed_at,
        version=item.version,
    )


def _raise_error(exc: RuntimeError) -> None:
    if isinstance(exc, MemoryNotFoundError):
        raise ApiError(status_code=404, code="MEMORY_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, MemoryConflictError):
        raise ApiError(status_code=409, code="MEMORY_CONFLICT", message=str(exc)) from exc
    raise exc


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    user_id: CurrentUserId,
    session: DbSession,
    category: Annotated[MemoryCategory | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> MemoryListResponse:
    items = await _service(session).list_memories(
        user_id=user_id,
        category=category,
        limit=limit,
    )
    return MemoryListResponse(list=[_response(item) for item in items])


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    body: MemoryCreateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> MemoryResponse:
    item = await _service(session).create(
        user_id=user_id,
        category=body.category,
        content=body.content,
    )
    return _response(item)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    body: MemoryUpdateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> MemoryResponse:
    try:
        item = await _service(session).update(
            user_id=user_id,
            memory_id=memory_id,
            expected_version=body.expected_version,
            category=body.category,
            content=body.content,
        )
    except RuntimeError as exc:
        _raise_error(exc)
    return _response(item)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    body: MemoryDeleteRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> Response:
    try:
        await _service(session).delete(
            user_id=user_id,
            memory_id=memory_id,
            expected_version=body.expected_version,
        )
    except RuntimeError as exc:
        _raise_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
