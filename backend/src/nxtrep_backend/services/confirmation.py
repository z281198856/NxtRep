from datetime import UTC, datetime
from uuid import UUID

from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository


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
            if item.operation_type in {"food_update", "food_delete"}:
                from nxtrep_backend.services.nutrition import (
                    NutritionConflictError,
                    NutritionNotFoundError,
                )

                if isinstance(exc, NutritionConflictError):
                    raise DatabaseConfirmationConflictError(
                        "食品已被修改，旧草稿未生效。请重新读取最新内容后生成草稿。",
                        item.version,
                    ) from exc
                if isinstance(exc, NutritionNotFoundError):
                    raise DatabaseConfirmationConflictError(
                        "食品已删除或当前账户无权修改，草稿未生效。请重新核对食品条目。",
                        item.version,
                    ) from exc
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
        if item.operation_type in {
            "workout_record_create",
            "workout_record_update",
            "workout_record_void",
        }:
            from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
            from nxtrep_backend.services.exercise import ExercisesService
            from nxtrep_backend.services.workout import WorkoutService
            from nxtrep_backend.services.workout_record import WorkoutRecordService

            service = WorkoutRecordService(
                WorkoutService(
                    SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
                ),
                self.repository,
                ExercisesService(SqlAlchemyExercisesRepository(session)),
            )
            if item.operation_type == "workout_record_create":
                return await service.execute_record(item)
            return await service.execute_change(item)
        if item.operation_type in {"workout_set_update", "workout_set_void"}:
            from nxtrep_backend.schemas.workout import (
                WorkoutSetUpdateRequest,
                WorkoutSetVoidRequest,
            )
            from nxtrep_backend.services.workout import (
                WorkoutConflictError,
                WorkoutNotFoundError,
                WorkoutService,
            )

            service = WorkoutService(
                SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
            )
            workout_id, set_id = UUID(item.after["workout_id"]), UUID(item.after["set_id"])
            data = {"reason": item.reason, "expected_version": item.after["expected_version"]}
            try:
                current_workout = await service.repository.get_workout(
                    item.user_id, workout_id, lock=True
                )
                if (
                    current_workout is None
                    or current_workout.version != item.after["expected_workout_version"]
                ):
                    raise WorkoutConflictError("训练记录版本变化")
                if item.operation_type == "workout_set_update":
                    result = await service.update_set(
                        item.user_id,
                        workout_id,
                        set_id,
                        WorkoutSetUpdateRequest.model_validate({**item.after["changes"], **data}),
                    )
                else:
                    result = await service.void_set(
                        item.user_id, workout_id, set_id, WorkoutSetVoidRequest.model_validate(data)
                    )
            except (WorkoutConflictError, WorkoutNotFoundError) as exc:
                raise RuntimeError(
                    "训练组不存在、已作废或被修改，旧草稿未生效。请重新读取记录。"
                ) from exc
            return {"resource_id": str(result.id), "resource_version": result.version}
        if item.operation_type == "profile_update":
            from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
            from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
            from nxtrep_backend.schemas.profile import ProfileUpdateRequest
            from nxtrep_backend.services.profile import ProfileService, ProfileVersionConflictError

            body = ProfileUpdateRequest.model_validate(
                {**item.after["changes"], "expected_version": item.after["expected_version"]}
            )
            try:
                profile = await ProfileService(
                    SqlAlchemyProfileRepository(session), SqlAlchemyBodyRepository(session)
                ).update_profile(
                    user_id=item.user_id,
                    changes=body.model_dump(exclude_unset=True, exclude={"expected_version"}),
                    expected_version=body.expected_version,
                )
            except ProfileVersionConflictError as exc:
                raise RuntimeError(
                    "个人资料已被修改，旧草稿未生效。请读取最新资料后重新生成草稿。"
                ) from exc
            return {"resource_id": str(profile.user_id), "resource_version": profile.version}
        if item.operation_type in {"food_update", "food_delete"}:
            from nxtrep_backend.schemas.nutrition import FoodUpdateRequest
            from nxtrep_backend.services.nutrition import NutritionService

            service = NutritionService(SqlAlchemyNutritionRepository(session))
            food_id = UUID(item.after["food_id"])
            expected = int(item.after["expected_version"])
            if item.operation_type == "food_delete":
                await service.delete_food(item.user_id, food_id, expected)
                return {"resource_id": str(food_id), "deleted": True}
            draft = item.after["food"]
            food, version = await service.update_food(
                item.user_id,
                food_id,
                FoodUpdateRequest.model_validate(
                    {
                        **{
                            field: draft[field]
                            for field in FoodUpdateRequest.model_fields
                            if field != "expected_version"
                        },
                        "expected_version": expected,
                    }
                ),
                source=draft["source"],
                confidence=draft["confidence"],
            )
            return {
                "resource_id": str(food.id),
                "resource_version": version.version,
                "food_version_id": str(version.id),
            }
        if item.operation_type == "food_create":
            from nxtrep_backend.schemas.nutrition import CustomFoodDraftRequest, FoodCreateRequest
            from nxtrep_backend.services.nutrition import NutritionService

            draft = CustomFoodDraftRequest.model_validate(item.after["food"])
            food, version = await NutritionService(
                SqlAlchemyNutritionRepository(session)
            ).create_food(
                item.user_id,
                FoodCreateRequest.model_validate(
                    draft.model_dump(exclude={"source", "confidence", "notes"})
                ),
                source=draft.source,
                confidence=draft.confidence,
            )
            return {
                "resource_id": str(food.id),
                "resource_version": version.version,
                "food_version_id": str(version.id),
            }
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
        if item.operation_type == "nutrition_entries_date_change":
            from nxtrep_backend.schemas.nutrition import NutritionDateChangeRequest
            from nxtrep_backend.services.nutrition import NutritionService

            return await NutritionService(
                SqlAlchemyNutritionRepository(session)
            ).apply_saved_date_change(
                item.user_id, NutritionDateChangeRequest.model_validate(item.after["request"])
            )
        if item.operation_type == "nutrition_entry_update":
            from nxtrep_backend.schemas.nutrition import NutritionSavedEntryRevisionRequest
            from nxtrep_backend.services.nutrition import NutritionService

            entry = await NutritionService(
                SqlAlchemyNutritionRepository(session)
            ).correct_saved_entry(
                item.user_id,
                UUID(item.after["entry_id"]),
                NutritionSavedEntryRevisionRequest(
                    expected_version=item.after["expected_version"],
                    changes=item.after.get("changes", []),
                    remove_item_indices=item.after.get("remove_item_indices", []),
                    reason=item.reason,
                ),
            )
            return {"resource_id": str(entry.id), "resource_version": entry.version}
        if item.operation_type == "nutrition_entry_delete":
            from nxtrep_backend.services.nutrition import NutritionService

            return await NutritionService(SqlAlchemyNutritionRepository(session)).delete_entry(
                item.user_id,
                UUID(item.after["entry_id"]),
                int(item.after["expected_version"]),
                reason=item.reason,
            )
        if item.operation_type == "water_entry_create":
            from nxtrep_backend.repositories.water import SqlAlchemyWaterRepository
            from nxtrep_backend.schemas.water import WaterEntryCreateRequest

            body = WaterEntryCreateRequest.model_validate(item.after["water"])
            entry = await SqlAlchemyWaterRepository(session).create(
                item.user_id, body.amount_ml, body.consumed_at
            )
            return {"resource_id": str(entry.id)}
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
        if item.status == "expired":
            raise DatabaseConfirmationConflictError("Confirmation has expired", item.version)
        if item.version != expected_version or item.status != "pending":
            raise DatabaseConfirmationConflictError("Confirmation was modified", item.version)
