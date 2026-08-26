from typing import Annotated
from uuid import UUID

from fastapi import Header, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.repositories.idempotency import SqlAlchemyIdempotencyRepository
from nxtrep_backend.services.idempotency import (
    IdempotencyDecision,
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
    IdempotencyService,
    IdempotencyStateError,
)

IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


async def begin_idempotent(
    session: AsyncSession,
    user_id: UUID,
    key: UUID,
    operation: str,
    payload: dict,
) -> tuple[IdempotencyService, IdempotencyDecision]:
    service = IdempotencyService(SqlAlchemyIdempotencyRepository(session))
    try:
        decision = await service.begin(
            user_id=user_id,
            idempotency_key=key,
            operation=operation,
            payload=payload,
        )
    except IdempotencyKeyConflictError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_KEY_CONFLICT",
            message="Idempotency key was reused with a different request",
        ) from exc
    except IdempotencyRequestInProgressError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_REQUEST_IN_PROGRESS",
            message="Idempotent request is still processing",
        ) from exc
    except IdempotencyStateError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="IDEMPOTENCY_STATE_INVALID",
            message="Idempotency record state is invalid",
        ) from exc
    return service, decision


def replay_response[ResponseModel: BaseModel](
    decision: IdempotencyDecision, model: type[ResponseModel], expected_status: int
) -> ResponseModel | None:
    if not decision.replayed:
        return None
    if decision.response_status != expected_status or not isinstance(decision.response_body, dict):
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="IDEMPOTENCY_STATE_INVALID",
            message="Stored idempotency response is invalid",
        )
    try:
        return model.model_validate(decision.response_body)
    except ValidationError as exc:
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="IDEMPOTENCY_STATE_INVALID",
            message="Stored idempotency response is invalid",
        ) from exc


async def complete_idempotent(
    service: IdempotencyService,
    decision: IdempotencyDecision,
    response: BaseModel,
    response_status: int,
) -> None:
    await service.complete(
        decision=decision,
        response_status=response_status,
        response_body=response.model_dump(mode="json"),
    )
