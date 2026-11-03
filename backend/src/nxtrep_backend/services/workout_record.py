"""Confirmed chat recording, built on the existing workout commands."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.schemas.workout import (
    WorkoutCreateRequest,
    WorkoutExerciseAddRequest,
    WorkoutSetCreateRequest,
    WorkoutSetUpdateRequest,
    WorkoutSetVoidRequest,
)
from nxtrep_backend.schemas.workout_record import (
    WorkoutRecordDraftRequest,
    WorkoutRecordUpdateRequest,
    WorkoutRecordVoidRequest,
)
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.workout import (
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutService,
)

LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


def _normalized(value: str) -> str:
    return "".join(value.casefold().split())


def _variant_conflicts(name: str, exercise) -> bool:
    """Only reject explicit equipment/angle contradictions, not general synonyms."""
    requested, actual = _normalized(name), _normalized(exercise.name_zh)
    equipment = exercise.equipment.casefold()
    constraints = (
        (r"史密斯|smith", {"smith", "smith_machine"}, r"史密斯|smith"),
        (r"哑铃|dumbbell", {"dumbbell"}, r"哑铃|dumbbell"),
        (r"杠铃|barbell", {"barbell"}, r"杠铃|barbell"),
        (r"绳索|龙门架|cable", {"cable"}, r"绳索|龙门架|cable"),
    )
    for pattern, allowed, label in constraints:
        if pattern == r"杠铃|barbell" and re.search(r"史密斯|smith", requested):
            continue
        if (
            re.search(pattern, requested)
            and equipment not in allowed
            and not re.search(label, actual)
        ):
            return True
    for angle in (r"上斜|incline", r"下斜|decline"):
        if re.search(angle, requested) and not re.search(angle, actual):
            return True
    return bool(
        re.search(r"平板|flat", requested) and re.search(r"上斜|下斜|incline|decline", actual)
    )


class WorkoutRecordService:
    def __init__(
        self,
        workout_service: WorkoutService,
        confirmation_repository: SqlAlchemyConfirmationRepository,
        exercises_service: ExercisesService,
    ) -> None:
        self.workout_service = workout_service
        self.confirmations = confirmation_repository
        self.exercises_service = exercises_service

    async def _resolve_exercise(self, user_id: UUID, body: WorkoutRecordDraftRequest):
        if body.exercise_id is not None:
            exercise = await self.workout_service.repository.get_exercise(user_id, body.exercise_id)
            if exercise is None:
                raise WorkoutNotFoundError("动作不存在、已删除或当前账户无权使用。")
            if body.exercise_name and _variant_conflicts(body.exercise_name, exercise):
                return {
                    "status": "needs_review",
                    "error_code": "EXERCISE_VARIANT_MISMATCH",
                    "missing_fields": ["exercise_id"],
                    "message": f"你要记录的是{body.exercise_name}，所选动作却是{exercise.name_zh}，"
                    "器械或角度不一致，不能替换记录。请查找原动作，不要用备注代替。",
                }
            return exercise
        if not body.exercise_name:
            return {
                "status": "needs_review",
                "missing_fields": ["exercise_name"],
                "message": "要记录哪个动作？",
            }
        result = await self.exercises_service.list_exercises(
            user_id=user_id,
            keyword=body.exercise_name,
            equipment=None,
            muscle=None,
            page=1,
            page_size=100,
        )
        keyword = _normalized(body.exercise_name)
        exact = [
            entry
            for entry in result.items
            if keyword
            in {
                _normalized(entry.exercise.name_zh),
                *(_normalized(alias) for alias in entry.aliases),
            }
        ]
        candidates = exact or result.items
        if len(candidates) != 1 or (not exact and result.has_more):
            return {
                "status": "needs_review",
                "missing_fields": ["exercise_id"],
                "message": "找到多个可能的动作，请选择具体动作。"
                if candidates
                else "没有找到这个动作，请核对名称或选择动作库中的动作。",
                "candidates": [
                    {
                        "exercise_id": str(entry.exercise.id),
                        "exercise_name": entry.exercise.name_zh,
                        "equipment": entry.exercise.equipment,
                    }
                    for entry in candidates[:20]
                ],
            }
        exercise = candidates[0].exercise
        if _variant_conflicts(body.exercise_name, exercise):
            return {
                "status": "needs_review",
                "error_code": "EXERCISE_VARIANT_MISMATCH",
                "missing_fields": ["exercise_id"],
                "message": "搜索结果的器械或角度与原动作不同，请查找原动作，不能用相近动作替换。",
            }
        return exercise

    async def propose_record(
        self,
        user_id: UUID,
        body: WorkoutRecordDraftRequest,
        *,
        conversation_id: UUID | None = None,
    ) -> Confirmation | dict:
        missing = [name for name in ("weight_kg", "sets", "reps") if getattr(body, name) is None]
        if body.exercise_id is None and not body.exercise_name:
            missing.insert(0, "exercise_name")
        if missing:
            return {
                "status": "needs_review",
                "missing_fields": missing,
                "message": "记录尚未保存，请补充动作、重量、组数和每组次数中缺少的信息。",
            }
        exercise = await self._resolve_exercise(user_id, body)
        if isinstance(exercise, dict):
            return exercise
        now = datetime.now(LOCAL_ZONE)
        workout_date = body.workout_date or (
            body.started_at.astimezone(LOCAL_ZONE).date() if body.started_at else now.date()
        )
        started_at = body.started_at or now.replace(
            year=workout_date.year, month=workout_date.month, day=workout_date.day
        )
        if started_at.astimezone(LOCAL_ZONE).date() != workout_date:
            raise WorkoutConflictError("训练日期与开始时间不一致，请核对。")
        if started_at > now:
            raise WorkoutConflictError("不能把尚未发生的训练记录为已完成的训练组。")
        expected_version = body.expected_workout_version
        if body.workout_id is not None:
            workout = await self.workout_service.repository.get_workout(user_id, body.workout_id)
            if workout is None:
                raise WorkoutNotFoundError("训练不存在或当前账户无权修改。")
            if expected_version is None:
                return {
                    "status": "needs_review",
                    "missing_fields": ["expected_workout_version"],
                    "message": "请先读取要追加的训练最新版本。",
                }
            if workout.status != "in_progress" or workout.version != expected_version:
                raise WorkoutConflictError(
                    "训练已暂停、结束或版本变化，请重新读取。", workout.version
                )
            if workout.started_at.astimezone(LOCAL_ZONE).date() != workout_date:
                raise WorkoutConflictError("追加动作的日期与原训练不同，请核对。")
            started_at = workout.started_at
        else:
            active = await self.workout_service.repository.get_active(user_id)
            if active is not None:
                return {
                    "status": "needs_review",
                    "missing_fields": ["workout_id"],
                    "message": "已有未结束训练，请明确追加到该训练，或先在训练页结束它。",
                    "candidates": [
                        {
                            "workout_id": str(active.id),
                            "expected_workout_version": active.version,
                            "date": active.started_at.astimezone(LOCAL_ZONE).date().isoformat(),
                            "status": active.status,
                        }
                    ],
                }
        request = body.model_dump(mode="json", exclude_none=True)
        request.update(
            exercise_id=str(exercise.id),
            exercise_name=exercise.name_zh,
            workout_date=workout_date.isoformat(),
            started_at=started_at.isoformat(),
        )
        proposal_metadata = {}
        if conversation_id is not None:
            identity = {
                key: request.get(key)
                for key in (
                    "exercise_id",
                    "workout_id",
                    "workout_date",
                    "expected_workout_version",
                    "sets",
                    "reps",
                    "notes",
                )
            }
            identity["weight_kg"] = format(body.weight_kg.normalize(), "f")
            identity["started_at"] = (
                body.started_at.isoformat() if body.started_at and not body.workout_id else None
            )
            proposal_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            existing = await self.confirmations.find_pending_workout_proposal(
                user_id,
                conversation_id,
                proposal_key,
            )
            if existing is not None:
                return existing
            proposal_metadata = {
                "proposal_conversation_id": str(conversation_id),
                "proposal_key": proposal_key,
            }
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="workout_record_create",
                before=None,
                after={
                    **proposal_metadata,
                    "request": request,
                    "exercise_version": exercise.version,
                    "preview": {
                        "date": workout_date.isoformat(),
                        "exercise_name": exercise.name_zh,
                        "weight_kg": str(body.weight_kg),
                        "sets": body.sets,
                        "reps": body.reps,
                        "workout_id": str(body.workout_id) if body.workout_id else None,
                    },
                },
                reason="按用户提供的实际训练数据记录。",
                impact="确认后记录该动作的实际训练组。训练保持进行中，追加其他动作时须重新提供重量、组数和次数。",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def read_for_change(
        self,
        user_id: UUID,
        workout_id: UUID | None = None,
        workout_date=None,
        exercise_name: str | None = None,
        workout_exercise_id: UUID | None = None,
    ) -> dict:
        if workout_id is None:
            if workout_date is None:
                return {
                    "status": "needs_review",
                    "missing_fields": ["workout_id"],
                    "message": "请明确要修改的训练日期或训练记录。",
                }
            history = await self.workout_service.list_history(
                user_id=user_id,
                start_date=workout_date,
                end_date=workout_date,
                status=None,
                page=1,
                page_size=100,
            )
            ids = [item.id for item in history.list]
            if history.has_more:
                return {
                    "status": "needs_review",
                    "missing_fields": ["workout_id"],
                    "message": "当天训练较多，请选择具体训练记录。",
                }
        else:
            ids = [workout_id]
        candidates = []
        for identifier in ids:
            aggregate = await self.workout_service.get_aggregate(user_id, identifier)
            local_date = aggregate.workout.started_at.astimezone(LOCAL_ZONE).date()
            if workout_date is not None and local_date != workout_date:
                continue
            for exercise in aggregate.exercises:
                if workout_exercise_id is not None and exercise.id != workout_exercise_id:
                    continue
                if exercise_name and _normalized(exercise_name) not in _normalized(
                    exercise.name_snapshot
                ):
                    continue
                sets = aggregate.sets_by_exercise.get(exercise.id, [])
                if not sets:
                    continue
                candidates.append(
                    {
                        "workout_id": str(identifier),
                        "workout_exercise_id": str(exercise.id),
                        "exercise_id": str(exercise.exercise_id) if exercise.exercise_id else None,
                        "exercise_name": exercise.name_snapshot,
                        "date": local_date.isoformat(),
                        "status": aggregate.workout.status,
                        "expected_workout_version": aggregate.workout.version,
                        "set_versions": [
                            {"set_id": str(item.id), "expected_version": item.version}
                            for item in sets
                        ],
                        "sets": [
                            {
                                "set_id": str(item.id),
                                "version": item.version,
                                "set_index": item.set_index,
                                "weight_kg": str(item.weight_kg),
                                "reps": item.reps,
                            }
                            for item in sets
                        ],
                    }
                )
        if exercise_name:
            exact = [
                entry
                for entry in candidates
                if _normalized(entry["exercise_name"]) == _normalized(exercise_name)
            ]
            candidates = exact or candidates
        if len(candidates) != 1:
            return {
                "status": "needs_review",
                "missing_fields": ["workout_exercise_id"],
                "candidates": candidates,
                "message": "有多个可能的动作记录，请选择具体训练和动作。"
                if candidates
                else "未找到对应有效训练组，请核对日期和动作。",
            }
        return {"status": "available", "selected_record": candidates[0]}

    async def _preflight_change(
        self, user_id, workout_id, workout_exercise_id, body, *, lock=False
    ):
        repository = self.workout_service.repository
        workout = await repository.get_workout(user_id, workout_id, lock=lock)
        if workout is None:
            raise WorkoutNotFoundError("训练不存在或当前账户无权修改。")
        if workout.version != body.expected_workout_version:
            raise WorkoutConflictError("训练已变化，请重新读取后生成草稿。", workout.version)
        exercise = await repository.get_workout_exercise(workout_id, workout_exercise_id, lock=lock)
        if exercise is None:
            raise WorkoutNotFoundError("该动作不属于所选训练。")
        aggregate = await self.workout_service.get_aggregate(user_id, workout_id)
        active_sets = aggregate.sets_by_exercise.get(workout_exercise_id, [])
        if {item.id for item in active_sets} != {item.set_id for item in body.set_versions}:
            raise WorkoutConflictError(
                "动作的有效训练组已变化，请重新读取；整动作更正须包含全部有效组。"
            )
        sets = []
        for version in body.set_versions:
            item = await repository.get_set(workout_id, version.set_id, lock=lock)
            if (
                item is None
                or item.workout_exercise_id != workout_exercise_id
                or item.voided_at is not None
                or item.version != version.expected_version
            ):
                raise WorkoutConflictError("训练组已被修改或作废，请重新读取后生成草稿。")
            sets.append(item)
        return workout, exercise, sorted(sets, key=lambda item: item.set_index)

    @staticmethod
    def _change_layout(sets, body):
        """Compute count changes once; never infer varying weights for added sets."""
        count = body.sets if body.sets is not None else len(sets)
        values = {}
        if count > len(sets):
            for key in ("weight_kg", "reps"):
                value = getattr(body, key)
                existing = {getattr(item, key) for item in sets}
                if value is None:
                    if len(existing) != 1:
                        raise WorkoutConflictError(
                            "原有各组的重量或次数不同，请补充新增组的重量和次数；尚未生成部分草稿。"
                        )
                    value = next(iter(existing))
                values[key] = value
        return sets[:count], sets[count:], count - min(count, len(sets)), values

    async def propose_change(
        self,
        user_id: UUID,
        workout_id: UUID,
        workout_exercise_id: UUID,
        body: WorkoutRecordUpdateRequest | WorkoutRecordVoidRequest,
    ) -> Confirmation:
        workout, exercise, sets = await self._preflight_change(
            user_id, workout_id, workout_exercise_id, body
        )
        is_void = isinstance(body, WorkoutRecordVoidRequest)
        before_sets = [
            {
                "set_id": str(item.id),
                "set_index": item.set_index,
                "weight_kg": str(item.weight_kg),
                "reps": item.reps,
            }
            for item in sets
        ]
        changes = body.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"set_versions", "expected_workout_version", "reason", "sets"},
        )
        after_sets = []
        if not is_void:
            retained, _, added_count, added_values = self._change_layout(sets, body)
            retained_ids = {str(item.id) for item in retained}
            after_sets = [
                {**item, **changes} for item in before_sets if item["set_id"] in retained_ids
            ]
            if added_count:
                next_index = await self.workout_service.repository.next_set_index(
                    workout_exercise_id
                )
                after_sets.extend(
                    {
                        "set_id": None,
                        "set_index": next_index + index,
                        "weight_kg": str(added_values["weight_kg"]),
                        "reps": added_values["reps"],
                        "added": True,
                    }
                    for index in range(added_count)
                )
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="workout_record_void" if is_void else "workout_record_update",
                before={"sets": before_sets},
                after={
                    "workout_id": str(workout_id),
                    "workout_exercise_id": str(workout_exercise_id),
                    "request": body.model_dump(mode="json", exclude_unset=True),
                    "preview": {
                        "date": workout.started_at.astimezone(LOCAL_ZONE).date().isoformat(),
                        "exercise_name": exercise.name_snapshot,
                        "before_sets": before_sets,
                        "after_sets": after_sets,
                    },
                },
                reason=body.reason,
                impact="确认后更正或作废所选动作的实际训练组，保留修订历史；其他动作和训练计划不受影响。",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def execute_record(self, card: Confirmation) -> dict:
        body = WorkoutRecordDraftRequest.model_validate(card.after["request"])
        if any(
            getattr(body, name) is None
            for name in ("exercise_id", "weight_kg", "sets", "reps", "started_at")
        ):
            raise WorkoutConflictError("训练草稿参数不完整，尚未生效。")
        repository = self.workout_service.repository
        async with repository.session.begin_nested():
            await repository.lock_record_owner(card.user_id)
            exercise = await repository.get_exercise(card.user_id, body.exercise_id)
            if exercise is None or exercise.version != card.after["exercise_version"]:
                raise WorkoutConflictError("动作已修改或删除，请重新生成草稿。")
            if body.workout_id is None:
                aggregate = await self.workout_service.create_workout(
                    card.user_id, WorkoutCreateRequest(started_at=body.started_at)
                )
                workout_id = aggregate.workout.id
            else:
                workout_id = body.workout_id
                workout = await repository.get_workout(card.user_id, workout_id, lock=True)
                if (
                    workout is None
                    or workout.status != "in_progress"
                    or workout.version != body.expected_workout_version
                ):
                    raise WorkoutConflictError("训练已变化，追加草稿尚未生效，请重新读取。")
            aggregate = await self.workout_service.get_aggregate(card.user_id, workout_id)
            before_ids = {item.id for item in aggregate.exercises}
            aggregate = await self.workout_service.add_exercise(
                card.user_id,
                workout_id,
                WorkoutExerciseAddRequest(
                    exercise_id=body.exercise_id,
                    target_sets=body.sets,
                    rep_min=body.reps,
                    rep_max=body.reps,
                    target_load_kg=body.weight_kg,
                    expected_workout_version=aggregate.workout.version,
                ),
            )
            item = next(item for item in aggregate.exercises if item.id not in before_ids)
            sets = []
            for index in range(1, body.sets + 1):
                sets.append(
                    await self.workout_service.create_set(
                        card.user_id,
                        workout_id,
                        WorkoutSetCreateRequest(
                            client_generated_id=uuid5(card.id, f"set:{index}"),
                            workout_exercise_id=item.id,
                            set_index=index,
                            weight_kg=body.weight_kg,
                            reps=body.reps,
                            notes=body.notes,
                            completed_at=body.started_at,
                            tags=["working"],
                        ),
                    )
                )
            workout = await repository.get_workout(card.user_id, workout_id)
            result = {
                "success": True,
                "resource_id": str(workout_id),
                "resource_version": workout.version,
                "workout_id": str(workout_id),
                "workout_exercise_id": str(item.id),
                "exercise_id": str(body.exercise_id),
                "exercise_name": item.name_snapshot,
                "date": body.workout_date.isoformat(),
                "status": workout.status,
                "expected_workout_version": workout.version,
                "set_versions": [
                    {"set_id": str(entry.id), "expected_version": entry.version} for entry in sets
                ],
                "sets": [
                    {
                        "set_id": str(entry.id),
                        "weight_kg": str(entry.weight_kg),
                        "reps": entry.reps,
                        "version": entry.version,
                    }
                    for entry in sets
                ],
            }
        return result

    async def execute_change(self, card: Confirmation) -> dict:
        is_void = card.operation_type == "workout_record_void"
        model = WorkoutRecordVoidRequest if is_void else WorkoutRecordUpdateRequest
        body = model.model_validate(card.after["request"])
        workout_id, item_id = (
            UUID(card.after["workout_id"]),
            UUID(card.after["workout_exercise_id"]),
        )
        repository = self.workout_service.repository
        async with repository.session.begin_nested():
            workout, exercise, current_sets = await self._preflight_change(
                card.user_id, workout_id, item_id, body, lock=True
            )
            changed = []
            if is_void:
                removed, added_count, added_values = current_sets, 0, {}
            else:
                _, removed, added_count, added_values = self._change_layout(current_sets, body)
            removed_ids = {item.id for item in removed}
            for existing in current_sets:
                if existing.id in removed_ids:
                    item = await self.workout_service.void_set(
                        card.user_id,
                        workout_id,
                        existing.id,
                        WorkoutSetVoidRequest(
                            expected_version=existing.version, reason=body.reason
                        ),
                    )
                else:
                    changes = body.model_dump(exclude_unset=True, include={"weight_kg", "reps"})
                    item = existing
                    if changes:
                        item = await self.workout_service.update_set(
                            card.user_id,
                            workout_id,
                            existing.id,
                            WorkoutSetUpdateRequest(
                                **changes, reason=body.reason, expected_version=existing.version
                            ),
                        )
                    changed.append(item)
            if added_count:
                next_index = await repository.next_set_index(item_id)
                for index in range(added_count):
                    changed.append(
                        await self.workout_service.create_set(
                            card.user_id,
                            workout_id,
                            WorkoutSetCreateRequest(
                                client_generated_id=uuid5(card.id, f"added-set:{index}"),
                                workout_exercise_id=item_id,
                                set_index=next_index + index,
                                weight_kg=added_values["weight_kg"],
                                reps=added_values["reps"],
                                completed_at=current_sets[-1].completed_at,
                                tags=["working"],
                                notes=body.reason,
                            ),
                            confirmed_correction=True,
                        )
                    )
            result = {
                "success": True,
                "resource_id": str(workout_id),
                "resource_version": workout.version,
                "workout_id": str(workout_id),
                "workout_exercise_id": str(item_id),
                "exercise_id": str(exercise.exercise_id) if exercise.exercise_id else None,
                "exercise_name": exercise.name_snapshot,
                "date": workout.started_at.astimezone(LOCAL_ZONE).date().isoformat(),
                "status": workout.status,
                "voided": is_void,
                "expected_workout_version": workout.version,
                "set_versions": []
                if is_void
                else [
                    {"set_id": str(item.id), "expected_version": item.version} for item in changed
                ],
                "sets": []
                if is_void
                else [
                    {
                        "set_id": str(item.id),
                        "weight_kg": str(item.weight_kg),
                        "reps": item.reps,
                        "version": item.version,
                    }
                    for item in changed
                ],
            }
        return result
