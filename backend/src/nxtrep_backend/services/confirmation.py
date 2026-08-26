from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.domain.confirmation import ConfirmationDraft, ConfirmationNotFoundError
from nxtrep_backend.repositories.confirmation import (
    ConfirmationRepository,
    InMemoryConfirmationRepository,
    SqlAlchemyConfirmationRepository,
)
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
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


class DatabaseConfirmationNotFoundError(RuntimeError):
    pass


class DatabaseConfirmationConflictError(RuntimeError):
    def __init__(self, message: str, current_version: int | None = None) -> None:
        super().__init__(message)
        self.current_version = current_version


class DatabaseConfirmationService:
    """Persists decisions and dispatches the approved command in one transaction."""

    def __init__(self, repository: SqlAlchemyConfirmationRepository) -> None:
        self.repository = repository

    async def list(self, user_id: UUID, status: str | None, page: int, page_size: int):
        return await self.repository.list_confirmations(user_id, status, page, page_size)

    async def approve(
        self, user_id: UUID, confirmation_id: UUID, expected_version: int
    ) -> Confirmation:
        item = await self.repository.get_confirmation(user_id, confirmation_id, lock=True)
        self._check_pending(item, expected_version)
        if item is None:  # narrows type for static checkers
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        if item.expires_at <= datetime.now(UTC):
            item.status = "expired"
            item.version += 1
            raise DatabaseConfirmationConflictError("Confirmation has expired", item.version)
        try:
            item.result = await self._execute(item)
        except RuntimeError as exc:
            raise DatabaseConfirmationConflictError(str(exc), item.version) from exc
        item.status = "succeeded"
        item.executed_at = datetime.now(UTC)
        item.version += 1
        await self.repository.session.flush()
        return item

    async def reject(
        self, user_id: UUID, confirmation_id: UUID, expected_version: int, reason: str | None
    ) -> Confirmation:
        item = await self.repository.get_confirmation(user_id, confirmation_id, lock=True)
        self._check_pending(item, expected_version)
        if item is None:
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        item.status = "rejected"
        item.rejection_reason = reason
        item.executed_at = datetime.now(UTC)
        item.version += 1
        await self.repository.session.flush()
        return item

    async def _execute(self, item: Confirmation) -> dict:
        session = self.repository.session
        if item.operation_type == "training_plan_activate":
            from nxtrep_backend.services.training import TrainingService

            return await TrainingService(SqlAlchemyTrainingRepository(session)).activate_draft(
                item.user_id,
                UUID(item.after["plan_draft_id"]),
                int(item.after["draft_version"]),
            )
        if item.operation_type == "calendar_reschedule":
            from nxtrep_backend.services.training import TrainingService

            return await TrainingService(SqlAlchemyTrainingRepository(session)).apply_reschedule(
                item.user_id, UUID(item.after["draft_id"]), int(item.after["draft_version"])
            )
        if item.operation_type == "nutrition_target_activate":
            from nxtrep_backend.services.nutrition import NutritionService

            return await NutritionService(SqlAlchemyNutritionRepository(session)).activate_target(
                item.user_id, UUID(item.after["target_id"]), int(item.after["draft_version"])
            )
        if item.operation_type == "training_progression_apply":
            from nxtrep_backend.services.workout import WorkoutService

            return await WorkoutService(
                SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
            ).apply_progression(
                item.user_id, UUID(item.after["draft_id"]), int(item.after["draft_version"])
            )
        raise DatabaseConfirmationConflictError(f"Unsupported operation {item.operation_type}")

    @staticmethod
    def _check_pending(item: Confirmation | None, expected_version: int) -> None:
        if item is None:
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        if item.version != expected_version or item.status != "pending":
            raise DatabaseConfirmationConflictError("Confirmation was modified", item.version)
