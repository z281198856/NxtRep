from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from nxtrep_backend.db.models import Exercise, ExerciseMuscle
from nxtrep_backend.repositories.exercise import (
    ExerciseDetailRecord,
    ExerciseListEntry,
    SqlAlchemyExercisesRepository,
)


@dataclass(frozen=True, slots=True)
class ExerciseListResult:
    items: list[ExerciseListEntry]
    total: int
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class ExerciseCreateData:
    name_zh: str
    equipment: str
    primary_muscles: list[str]
    secondary_muscles: list[str]
    notes: str | None


@dataclass(frozen=True, slots=True)
class ExerciseUpdateData:
    name_zh: str | None
    equipment: str | None
    primary_muscles: list[str] | None
    secondary_muscles: list[str] | None
    notes: str | None
    supplied_fields: frozenset[str]


class ExerciseNotFoundError(RuntimeError):
    """动作不存在、已被删除或当前用户无权查看。"""


class ExerciseVersionConflictError(RuntimeError):
    """客户端使用的动作版本已经过期。"""

    def __init__(
        self,
        *,
        expected_version: int,
        current_version: int,
    ) -> None:
        super().__init__("Exercise version conflict")
        self.expected_version = expected_version
        self.current_version = current_version


class ExerciseMuscleOverlapError(RuntimeError):
    """更新后的主要和次要肌群发生重叠。"""


class ExerciseStateError(RuntimeError):
    """动作更新后的数据库状态异常。"""


class ExercisesService:
    def __init__(
        self,
        repository: SqlAlchemyExercisesRepository,
    ) -> None:
        self._repository = repository

    async def list_exercises(
        self,
        *,
        user_id: UUID,
        keyword: str | None,
        equipment: str | None,
        muscle: str | None,
        page: int,
        page_size: int,
    ) -> ExerciseListResult:
        result = await self._repository.list_exercises(
            user_id=user_id,
            keyword=keyword,
            equipment=equipment,
            muscle=muscle,
            page=page,
            page_size=page_size,
        )

        return ExerciseListResult(
            items=result.items,
            total=result.total,
            page=page,
            page_size=page_size,
            has_more=page * page_size < result.total,
        )

    async def get_exercise_detail(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
    ) -> ExerciseDetailRecord:
        result = await self._repository.get_exercise_detail(
            user_id=user_id,
            exercise_id=exercise_id,
        )

        if result is None:
            raise ExerciseNotFoundError("Exercise not found")

        return result

    async def create_custom_exercise(
        self,
        *,
        user_id: UUID,
        data: ExerciseCreateData,
    ) -> ExerciseDetailRecord:
        exercise_id = uuid4()

        exercise = Exercise(
            id=exercise_id,
            owner_user_id=user_id,
            name_zh=data.name_zh,
            movement_pattern=None,
            equipment=data.equipment,
            difficulty=None,
            instructions=[],
            breathing=[],
            common_errors=[],
            safety_notes=[],
            notes=data.notes,
            version=1,
        )

        muscles = [
            ExerciseMuscle(
                exercise_id=exercise_id,
                muscle_code=muscle_code,
                role="primary",
            )
            for muscle_code in data.primary_muscles
        ]
        muscles.extend(
            ExerciseMuscle(
                exercise_id=exercise_id,
                muscle_code=muscle_code,
                role="secondary",
            )
            for muscle_code in data.secondary_muscles
        )

        await self._repository.save_custom_exercise(
            exercise=exercise,
            muscles=muscles,
        )

        return ExerciseDetailRecord(
            exercise=exercise,
            aliases=[],
            primary_muscles=list(data.primary_muscles),
            secondary_muscles=list(data.secondary_muscles),
            substitutions=[],
        )

    async def update_custom_exercise(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
        data: ExerciseUpdateData,
        expected_version: int,
    ) -> ExerciseDetailRecord:
        state = await self._repository.get_custom_exercise_for_update(
            user_id=user_id,
            exercise_id=exercise_id,
        )

        if state is None:
            raise ExerciseNotFoundError("Exercise not found")

        exercise = state.exercise

        if exercise.version != expected_version:
            raise ExerciseVersionConflictError(
                expected_version=expected_version,
                current_version=exercise.version,
            )

        primary_muscles = (
            list(data.primary_muscles)
            if "primary_muscles" in data.supplied_fields and data.primary_muscles is not None
            else list(state.primary_muscles)
        )
        secondary_muscles = (
            list(data.secondary_muscles)
            if "secondary_muscles" in data.supplied_fields and data.secondary_muscles is not None
            else list(state.secondary_muscles)
        )

        overlap = set(primary_muscles).intersection(secondary_muscles)
        if overlap:
            raise ExerciseMuscleOverlapError("A muscle cannot be both primary and secondary")

        if "name_zh" in data.supplied_fields and data.name_zh is not None:
            exercise.name_zh = data.name_zh

        if "equipment" in data.supplied_fields and data.equipment is not None:
            exercise.equipment = data.equipment

        if "notes" in data.supplied_fields:
            exercise.notes = data.notes

        exercise.version += 1

        muscles: list[ExerciseMuscle] | None = None
        muscle_fields = {
            "primary_muscles",
            "secondary_muscles",
        }

        if data.supplied_fields.intersection(muscle_fields):
            muscles = [
                ExerciseMuscle(
                    exercise_id=exercise.id,
                    muscle_code=muscle_code,
                    role="primary",
                )
                for muscle_code in primary_muscles
            ]
            muscles.extend(
                ExerciseMuscle(
                    exercise_id=exercise.id,
                    muscle_code=muscle_code,
                    role="secondary",
                )
                for muscle_code in secondary_muscles
            )

        await self._repository.save_custom_exercise_update(
            exercise=exercise,
            muscles=muscles,
        )

        result = await self._repository.get_exercise_detail(
            user_id=user_id,
            exercise_id=exercise.id,
        )

        if result is None:
            raise ExerciseStateError("Updated exercise could not be loaded")

        return result

    async def delete_custom_exercise(
        self,
        *,
        user_id: UUID,
        exercise_id: UUID,
        expected_version: int,
    ) -> None:
        state = await self._repository.get_custom_exercise_for_update(
            user_id=user_id,
            exercise_id=exercise_id,
        )

        if state is None:
            raise ExerciseNotFoundError("Exercise not found")

        exercise = state.exercise

        if exercise.version != expected_version:
            raise ExerciseVersionConflictError(
                expected_version=expected_version,
                current_version=exercise.version,
            )

        exercise.deleted_at = datetime.now(UTC)
        exercise.version += 1

        await self._repository.save_custom_exercise_update(
            exercise=exercise,
            muscles=None,
        )
