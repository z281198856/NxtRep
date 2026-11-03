from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Confirmation


class SqlAlchemyConfirmationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_confirmation(self, item: Confirmation) -> Confirmation:
        self.session.add(item)
        await self.session.flush()
        return item

    async def find_pending_workout_proposal(
        self,
        user_id: UUID,
        conversation_id: UUID,
        proposal_key: str,
    ) -> Confirmation | None:
        return await self.session.scalar(
            select(Confirmation)
            .where(
                Confirmation.user_id == user_id,
                Confirmation.operation_type == "workout_record_create",
                Confirmation.status == "pending",
                Confirmation.expires_at > datetime.now(UTC),
                Confirmation.after["proposal_conversation_id"].astext == str(conversation_id),
                Confirmation.after["proposal_key"].astext == proposal_key,
            )
            .order_by(Confirmation.created_at)
            .limit(1)
        )

    async def get_confirmation(
        self, user_id: UUID, confirmation_id: UUID, *, lock: bool = False
    ) -> Confirmation | None:
        await self._expire_pending(user_id, confirmation_id)
        statement = select(Confirmation).where(
            Confirmation.id == confirmation_id, Confirmation.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def _expire_pending(self, user_id: UUID, confirmation_id: UUID | None = None) -> None:
        conditions = [
            Confirmation.user_id == user_id,
            Confirmation.status == "pending",
            Confirmation.expires_at <= datetime.now(UTC),
        ]
        if confirmation_id is not None:
            conditions.append(Confirmation.id == confirmation_id)
        await self.session.execute(
            update(Confirmation)
            .where(*conditions)
            .values(status="expired", version=Confirmation.version + 1)
        )
        await self.session.flush()

    async def list_confirmations(
        self, user_id: UUID, status: str | None, page: int, page_size: int
    ) -> tuple[list[Confirmation], int]:
        await self._expire_pending(user_id)
        conditions = [Confirmation.user_id == user_id]
        if status:
            conditions.append(Confirmation.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(Confirmation).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(Confirmation)
                .where(*conditions)
                .order_by(Confirmation.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)
