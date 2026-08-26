import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from nxtrep_backend.repositories.idempotency import (
    SqlAlchemyIdempotencyRepository,
)


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    record_id: UUID
    replayed: bool
    response_status: int | None
    response_body: dict[str, Any] | list[Any] | None


class IdempotencyKeyConflictError(RuntimeError):
    """同一个幂等 Key 被用于不同请求。"""


class IdempotencyRequestInProgressError(RuntimeError):
    """相同幂等请求仍在处理中。"""


class IdempotencyStateError(RuntimeError):
    """幂等记录处于无法识别的状态。"""


class IdempotencyService:
    retention = timedelta(hours=24)

    def __init__(
        self,
        repository: SqlAlchemyIdempotencyRepository,
    ) -> None:
        self._repository = repository

    async def begin(
        self,
        *,
        user_id: UUID,
        idempotency_key: UUID,
        operation: str,
        payload: dict[str, Any],
    ) -> IdempotencyDecision:
        request_hash = self._hash_payload(payload)
        now = datetime.now(UTC)

        claim = await self._repository.claim(
            user_id=user_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            now=now,
            expires_at=now + self.retention,
        )

        if claim.acquired:
            return IdempotencyDecision(
                record_id=claim.record_id,
                replayed=False,
                response_status=None,
                response_body=None,
            )

        if claim.operation != operation or claim.request_hash != request_hash:
            raise IdempotencyKeyConflictError("Idempotency key was reused with a different request")

        if claim.status == "processing":
            raise IdempotencyRequestInProgressError("Idempotent request is still processing")

        if claim.status != "completed":
            raise IdempotencyStateError("Unknown idempotency record state")

        if claim.response_status is None:
            raise IdempotencyStateError("Completed idempotency record has no response status")

        return IdempotencyDecision(
            record_id=claim.record_id,
            replayed=True,
            response_status=claim.response_status,
            response_body=claim.response_body,
        )

    async def complete(
        self,
        *,
        decision: IdempotencyDecision,
        response_status: int,
        response_body: dict[str, Any] | list[Any] | None,
    ) -> None:
        if decision.replayed:
            raise ValueError("A replayed request cannot be completed again")

        await self._repository.complete(
            record_id=decision.record_id,
            response_status=response_status,
            response_body=response_body,
        )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
