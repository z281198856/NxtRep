from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.repositories.idempotency import (
    IdempotencyClaim,
    SqlAlchemyIdempotencyRepository,
)
from nxtrep_backend.services.idempotency import (
    IdempotencyDecision,
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
    IdempotencyService,
)


def make_repository() -> SqlAlchemyIdempotencyRepository:
    repository = MagicMock(spec=SqlAlchemyIdempotencyRepository)
    repository.claim = AsyncMock()
    repository.complete = AsyncMock()
    return repository


def test_hash_payload_is_stable_across_dictionary_order() -> None:
    first = IdempotencyService._hash_payload({"name_zh": "高脚杯深蹲", "equipment": "dumbbell"})
    second = IdempotencyService._hash_payload({"equipment": "dumbbell", "name_zh": "高脚杯深蹲"})

    assert first == second
    assert len(first) == 64


@pytest.mark.asyncio
async def test_begin_allows_new_request_and_sets_24_hour_expiration() -> None:
    repository = make_repository()
    record_id = uuid4()
    repository.claim.return_value = IdempotencyClaim(
        record_id=record_id,
        acquired=True,
        operation="POST /exercises",
        request_hash="ignored-for-new-claim",
        status="processing",
        response_status=None,
        response_body=None,
    )
    service = IdempotencyService(repository)

    decision = await service.begin(
        user_id=uuid4(),
        idempotency_key=uuid4(),
        operation="POST /exercises",
        payload={"name_zh": "高脚杯深蹲"},
    )

    assert decision == IdempotencyDecision(
        record_id=record_id,
        replayed=False,
        response_status=None,
        response_body=None,
    )
    claim_call = repository.claim.await_args
    assert claim_call.kwargs["expires_at"] - claim_call.kwargs["now"] == service.retention


@pytest.mark.asyncio
async def test_begin_replays_completed_matching_request() -> None:
    repository = make_repository()
    service = IdempotencyService(repository)
    payload = {"name_zh": "高脚杯深蹲"}
    request_hash = service._hash_payload(payload)
    record_id = uuid4()
    response_body = {"id": str(uuid4())}
    repository.claim.return_value = IdempotencyClaim(
        record_id=record_id,
        acquired=False,
        operation="POST /exercises",
        request_hash=request_hash,
        status="completed",
        response_status=201,
        response_body=response_body,
    )

    decision = await service.begin(
        user_id=uuid4(),
        idempotency_key=uuid4(),
        operation="POST /exercises",
        payload=payload,
    )

    assert decision.replayed is True
    assert decision.response_status == 201
    assert decision.response_body == response_body


@pytest.mark.asyncio
async def test_begin_rejects_key_reused_for_different_payload() -> None:
    repository = make_repository()
    repository.claim.return_value = IdempotencyClaim(
        record_id=uuid4(),
        acquired=False,
        operation="POST /exercises",
        request_hash="different-hash",
        status="completed",
        response_status=201,
        response_body={},
    )
    service = IdempotencyService(repository)

    with pytest.raises(IdempotencyKeyConflictError):
        await service.begin(
            user_id=uuid4(),
            idempotency_key=uuid4(),
            operation="POST /exercises",
            payload={"name_zh": "高脚杯深蹲"},
        )


@pytest.mark.asyncio
async def test_begin_rejects_matching_request_still_processing() -> None:
    repository = make_repository()
    service = IdempotencyService(repository)
    payload = {"name_zh": "高脚杯深蹲"}
    repository.claim.return_value = IdempotencyClaim(
        record_id=uuid4(),
        acquired=False,
        operation="POST /exercises",
        request_hash=service._hash_payload(payload),
        status="processing",
        response_status=None,
        response_body=None,
    )

    with pytest.raises(IdempotencyRequestInProgressError):
        await service.begin(
            user_id=uuid4(),
            idempotency_key=uuid4(),
            operation="POST /exercises",
            payload=payload,
        )


@pytest.mark.asyncio
async def test_complete_persists_new_request_response() -> None:
    repository = make_repository()
    service = IdempotencyService(repository)
    decision = IdempotencyDecision(
        record_id=uuid4(),
        replayed=False,
        response_status=None,
        response_body=None,
    )
    response_body = {"id": str(uuid4())}

    await service.complete(
        decision=decision,
        response_status=201,
        response_body=response_body,
    )

    repository.complete.assert_awaited_once_with(
        record_id=decision.record_id,
        response_status=201,
        response_body=response_body,
    )


@pytest.mark.asyncio
async def test_complete_rejects_replayed_request() -> None:
    repository = make_repository()
    service = IdempotencyService(repository)
    decision = IdempotencyDecision(
        record_id=uuid4(),
        replayed=True,
        response_status=201,
        response_body={},
    )

    with pytest.raises(ValueError):
        await service.complete(
            decision=decision,
            response_status=201,
            response_body={},
        )

    repository.complete.assert_not_awaited()
