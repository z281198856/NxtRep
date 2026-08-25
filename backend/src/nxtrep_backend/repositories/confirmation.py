from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

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
