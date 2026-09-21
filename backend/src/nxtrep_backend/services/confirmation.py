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

    async def get(
        self,
        *,
        user_id: UUID,
        confirmation_id: UUID,
    ) -> Confirmation:
        item = await self.repository.get_confirmation(user_id, confirmation_id)
        if item is None:
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        return item

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
        if item.expires_at <= datetime.now(UTC):
            item.status = "expired"
            item.version += 1
            raise DatabaseConfirmationConflictError("Confirmation has expired", item.version)
        item.status = "rejected"
        item.rejection_reason = reason
        item.executed_at = datetime.now(UTC)
        item.version += 1
        await self.repository.session.flush()
        return item

    async def cancel(
        self,
        user_id: UUID,
        confirmation_id: UUID,
        expected_version: int,
    ) -> Confirmation:
        item = await self.repository.get_confirmation(user_id, confirmation_id, lock=True)
        self._check_pending(item, expected_version)
        if item is None:
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        item.status = "cancelled"
        item.rejection_reason = "cancelled_by_user"
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
                UUID(item.after["base_plan_version_id"])
                if item.after.get("base_plan_version_id")
                else None,
            )
        if item.operation_type == "training_plan_archive":
            from nxtrep_backend.services.training import TrainingService

            return await TrainingService(SqlAlchemyTrainingRepository(session)).archive_plan(
                user_id=item.user_id,
                plan_id=UUID(item.after["plan_id"]),
                version_id=UUID(item.after["version_id"]),
                version=int(item.after["version"]),
            )
        if item.operation_type == "calendar_reschedule":
            from nxtrep_backend.services.training import TrainingService

            return await TrainingService(SqlAlchemyTrainingRepository(session)).apply_reschedule(
                item.user_id, UUID(item.after["draft_id"]), int(item.after["draft_version"])
            )
        if item.operation_type == "nutrition_target_activate":
            from nxtrep_backend.services.nutrition import NutritionService

            return await NutritionService(SqlAlchemyNutritionRepository(session)).activate_target(
                item.user_id,
                UUID(item.after["target_id"]),
                int(item.after["draft_version"]),
                UUID(item.after["base_target_version_id"])
                if item.after.get("base_target_version_id")
                else None,
            )
        if item.operation_type == "nutrition_entry_create":
            from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest
            from nxtrep_backend.services.nutrition import NutritionService

            entry = await NutritionService(SqlAlchemyNutritionRepository(session)).create_entry(
                item.user_id,
                NutritionEntryCreateRequest.model_validate(item.after["entry"]),
            )
            return {"resource_id": str(entry.id), "resource_version": entry.version}
        if item.operation_type == "nutrition_entry_delete":
            from nxtrep_backend.services.nutrition import NutritionService

            return await NutritionService(SqlAlchemyNutritionRepository(session)).delete_entry(
                item.user_id,
                UUID(item.after["entry_id"]),
                int(item.after["expected_version"]),
            )
        if item.operation_type == "body_measurement_create":
            from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
            from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest
            from nxtrep_backend.services.body import BodyService

            measurement = await BodyService(SqlAlchemyBodyRepository(session)).create_measurement(
                item.user_id,
                BodyMeasurementCreateRequest.model_validate(item.after["measurement"]),
            )
            return {
                "resource_id": str(measurement.id),
                "resource_version": measurement.version,
            }
        if item.operation_type == "body_measurement_delete":
            from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
            from nxtrep_backend.services.body import BodyService

            return await BodyService(SqlAlchemyBodyRepository(session)).delete_measurement(
                item.user_id,
                UUID(item.after["measurement_id"]),
                int(item.after["expected_version"]),
            )
        if item.operation_type == "memory_create":
            from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
            from nxtrep_backend.services.memory import MemoryService

            memory = await MemoryService(SqlAlchemyMemoryRepository(session)).create(
                user_id=item.user_id,
                category=item.after["category"],
                content=item.after["content"],
            )
            return {
                "resource_id": str(memory.id),
                "resource_version": memory.version,
            }
        if item.operation_type == "memory_update":
            from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
            from nxtrep_backend.services.memory import MemoryService

            memory = await MemoryService(SqlAlchemyMemoryRepository(session)).update(
                user_id=item.user_id,
                memory_id=UUID(item.after["memory_id"]),
                expected_version=int(item.after["expected_version"]),
                category=item.after["category"],
                content=item.after["content"],
            )
            return {
                "resource_id": str(memory.id),
                "resource_version": memory.version,
            }
        if item.operation_type == "memory_delete":
            from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
            from nxtrep_backend.services.memory import MemoryService

            memory = await MemoryService(SqlAlchemyMemoryRepository(session)).delete(
                user_id=item.user_id,
                memory_id=UUID(item.after["memory_id"]),
                expected_version=int(item.after["expected_version"]),
            )
            return {
                "resource_id": str(memory.id),
                "resource_version": memory.version,
            }
        if item.operation_type == "training_progression_apply":
            from nxtrep_backend.services.workout import WorkoutService

            return await WorkoutService(
                SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
            ).apply_progression(
                item.user_id,
                UUID(item.after["draft_id"]),
                int(item.after["draft_version"]),
                UUID(item.after["base_plan_version_id"])
                if item.after.get("base_plan_version_id")
                else None,
            )
        raise DatabaseConfirmationConflictError(f"Unsupported operation {item.operation_type}")

    @staticmethod
    def _check_pending(item: Confirmation | None, expected_version: int) -> None:
        if item is None:
            raise DatabaseConfirmationNotFoundError("Confirmation not found")
        if item.version != expected_version or item.status != "pending":
            raise DatabaseConfirmationConflictError("Confirmation was modified", item.version)
