from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import IdempotencyRecord
from nxtrep_backend.repositories.idempotency import (
    SqlAlchemyIdempotencyRepository,
)


@pytest.mark.asyncio
async def test_claim_acquires_new_idempotency_key() -> None:
    record_id = uuid4()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=record_id)
    repository = SqlAlchemyIdempotencyRepository(session)
    now = datetime.now(UTC)

    claim = await repository.claim(
        user_id=uuid4(),
        idempotency_key=uuid4(),
        operation="POST /exercises",
        request_hash="a" * 64,
        now=now,
        expires_at=now + timedelta(hours=24),
    )

    assert claim.record_id == record_id
    assert claim.acquired is True
    assert claim.status == "processing"
    assert claim.response_body is None
    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_claim_returns_existing_completed_record_for_replay() -> None:
    now = datetime.now(UTC)
    existing = IdempotencyRecord(
        id=uuid4(),
        user_id=uuid4(),
        idempotency_key=uuid4(),
        operation="POST /exercises",
        request_hash="b" * 64,
        status="completed",
        response_status=201,
        response_body={"id": str(uuid4())},
        expires_at=now + timedelta(hours=23),
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[None, existing])
    repository = SqlAlchemyIdempotencyRepository(session)

    claim = await repository.claim(
        user_id=existing.user_id,
        idempotency_key=existing.idempotency_key,
        operation="POST /exercises",
        request_hash="b" * 64,
        now=now,
        expires_at=now + timedelta(hours=24),
    )

    assert claim.acquired is False
    assert claim.status == "completed"
    assert claim.response_status == 201
    assert claim.response_body == existing.response_body
    assert session.scalar.await_count == 2


@pytest.mark.asyncio
async def test_claim_resets_expired_record() -> None:
    now = datetime.now(UTC)
    existing = IdempotencyRecord(
        id=uuid4(),
        user_id=uuid4(),
        idempotency_key=uuid4(),
        operation="POST /old-operation",
        request_hash="c" * 64,
        status="completed",
        response_status=201,
        response_body={"old": True},
        expires_at=now - timedelta(seconds=1),
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=[None, existing, existing.id])
    repository = SqlAlchemyIdempotencyRepository(session)

    claim = await repository.claim(
        user_id=existing.user_id,
        idempotency_key=existing.idempotency_key,
        operation="POST /exercises",
        request_hash="d" * 64,
        now=now,
        expires_at=now + timedelta(hours=24),
    )

    assert claim.acquired is True
    assert claim.operation == "POST /exercises"
    assert claim.request_hash == "d" * 64
    assert claim.response_body is None
    assert session.scalar.await_count == 3


@pytest.mark.asyncio
async def test_complete_transitions_processing_record() -> None:
    record_id = uuid4()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=record_id)
    repository = SqlAlchemyIdempotencyRepository(session)
    body = {"id": str(uuid4())}

    await repository.complete(
        record_id=record_id,
        response_status=201,
        response_body=body,
    )

    statement = session.scalar.await_args.args[0]
    assert statement.compile().params["response_status"] == 201
    assert statement.compile().params["response_body"] == body


@pytest.mark.asyncio
async def test_claim_rejects_non_future_expiration() -> None:
    session = MagicMock(spec=AsyncSession)
    repository = SqlAlchemyIdempotencyRepository(session)
    now = datetime.now(UTC)

    with pytest.raises(ValueError):
        await repository.claim(
            user_id=uuid4(),
            idempotency_key=uuid4(),
            operation="POST /exercises",
            request_hash="e" * 64,
            now=now,
            expires_at=now,
        )
