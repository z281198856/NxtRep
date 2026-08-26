from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.domain.confirmation import ConfirmationDraft


class ConfirmationRepository(Protocol):
    async def add(self, draft: ConfirmationDraft) -> None: ...

    async def get_for_user(
        self,
        confirmation_id: str,
        user_id: UUID,
    ) -> ConfirmationDraft | None: ...

    async def list_for_user(self, user_id: UUID) -> Iterable[ConfirmationDraft]: ...


class InMemoryConfirmationRepository:
    """Development implementation; replace with a transactional SQL repository."""

    def __init__(self) -> None:
        self._items: dict[str, ConfirmationDraft] = {}

    async def add(self, draft: ConfirmationDraft) -> None:
        self._items[draft.id] = draft

    async def get_for_user(
        self,
        confirmation_id: str,
        user_id: UUID,
    ) -> ConfirmationDraft | None:
        item = self._items.get(confirmation_id)
        return item if item is not None and item.user_id == user_id else None

    async def list_for_user(self, user_id: UUID) -> Iterable[ConfirmationDraft]:
        return (item for item in self._items.values() if item.user_id == user_id)


class SqlAlchemyConfirmationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_confirmation(self, item: Confirmation) -> Confirmation:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_confirmation(
        self, user_id: UUID, confirmation_id: UUID, *, lock: bool = False
    ) -> Confirmation | None:
        statement = select(Confirmation).where(
            Confirmation.id == confirmation_id, Confirmation.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_confirmations(
        self, user_id: UUID, status: str | None, page: int, page_size: int
    ) -> tuple[list[Confirmation], int]:
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
