from functools import lru_cache
from uuid import UUID

from nxtrep_backend.domain.confirmation import ConfirmationDraft, ConfirmationNotFoundError
from nxtrep_backend.repositories.confirmation import (
    ConfirmationRepository,
    InMemoryConfirmationRepository,
)
from nxtrep_backend.schemas.confirmation import ConfirmationCreate


class ConfirmationService:
    def __init__(self, repository: ConfirmationRepository) -> None:
        self._repository = repository

    async def create(self, user_id: UUID, data: ConfirmationCreate) -> ConfirmationDraft:
        draft = ConfirmationDraft(user_id=user_id, **data.model_dump())
        await self._repository.add(draft)
        return draft

    async def decide(
        self,
        user_id: UUID,
        confirmation_id: str,
        decision: str,
    ) -> ConfirmationDraft:
        draft = await self._repository.get_for_user(confirmation_id, user_id)
        if draft is None:
            raise ConfirmationNotFoundError(f"Confirmation {confirmation_id} was not found")
        draft.decide(decision)
        # Approval changes only the confirmation state in this scaffold. A later command
        # dispatcher must execute the operation transactionally and record its outcome.
        return draft


@lru_cache
def get_confirmation_service() -> ConfirmationService:
    return ConfirmationService(InMemoryConfirmationRepository())
