from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import IdempotencyRecord, IdempotencyStatus


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    record_id: UUID
    acquired: bool
    operation: str
    request_hash: str
    status: str
    response_status: int | None
    response_body: dict[str, Any] | list[Any] | None


class SqlAlchemyIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        *,
        user_id: UUID,
        idempotency_key: UUID,
        operation: str,
        request_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> IdempotencyClaim:
        if expires_at <= now:
            raise ValueError("expires_at must be later than now")

        record_id = uuid4()
        insert_statement = (
            insert(IdempotencyRecord)
            .values(
                id=record_id,
                user_id=user_id,
                idempotency_key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING.value,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecord.user_id,
                    IdempotencyRecord.idempotency_key,
                ]
            )
            .returning(IdempotencyRecord.id)
        )
        inserted_id = await self._session.scalar(insert_statement)

        if inserted_id is not None:
            return IdempotencyClaim(
                record_id=inserted_id,
                acquired=True,
                operation=operation,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING.value,
                response_status=None,
                response_body=None,
            )

        existing_statement = (
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        existing = await self._session.scalar(existing_statement)

        if existing is None:
            raise RuntimeError("Conflicting idempotency record was not found")

        if existing.expires_at <= now:
            reset_statement = (
                update(IdempotencyRecord)
                .where(IdempotencyRecord.id == existing.id)
                .values(
                    operation=operation,
                    request_hash=request_hash,
                    status=IdempotencyStatus.PROCESSING.value,
                    response_status=None,
                    response_body=None,
                    expires_at=expires_at,
                )
                .returning(IdempotencyRecord.id)
            )
            reset_id = await self._session.scalar(reset_statement)

            if reset_id is None:
                raise RuntimeError("Expired idempotency record could not be reset")

            return IdempotencyClaim(
                record_id=reset_id,
                acquired=True,
                operation=operation,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING.value,
                response_status=None,
                response_body=None,
            )

        return IdempotencyClaim(
            record_id=existing.id,
            acquired=False,
            operation=existing.operation,
            request_hash=existing.request_hash,
            status=existing.status,
            response_status=existing.response_status,
            response_body=existing.response_body,
        )

    async def complete(
        self,
        *,
        record_id: UUID,
        response_status: int,
        response_body: dict[str, Any] | list[Any] | None,
    ) -> None:
        statement = (
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == record_id,
                IdempotencyRecord.status == IdempotencyStatus.PROCESSING.value,
            )
            .values(
                status=IdempotencyStatus.COMPLETED.value,
                response_status=response_status,
                response_body=response_body,
            )
            .returning(IdempotencyRecord.id)
        )
        completed_id = await self._session.scalar(statement)

        if completed_id is None:
            raise RuntimeError("Idempotency record is not processing")
