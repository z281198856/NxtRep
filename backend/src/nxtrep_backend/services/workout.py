from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from nxtrep_backend.db.models import (
    Confirmation,
    PersonalRecord,
    ProgressionDraft,
    TrainingPlanVersion,
    Workout,
    WorkoutExercise,
    WorkoutSet,
    WorkoutSetRevision,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository, WorkoutAggregate
from nxtrep_backend.schemas.workout import (
    ProgressionDraftCreateRequest,
    WorkoutCreateRequest,
    WorkoutExerciseReplaceRequest,
    WorkoutFinishRequest,
    WorkoutSetCreateRequest,
    WorkoutSetUpdateRequest,
)


class WorkoutNotFoundError(RuntimeError):
    pass


class WorkoutConflictError(RuntimeError):
    def __init__(self, message: str, current_version: int | None = None) -> None:
        super().__init__(message)
        self.current_version = current_version


def set_payload(item: WorkoutSet) -> dict:
    return {
        "id": item.id,
        "set_index": item.set_index,
        "weight_kg": item.weight_kg,
        "reps": item.reps,
        "rir": item.rir,
        "rpe": item.rpe,
        "tags": item.tags,
        "notes": item.notes,
        "completed_at": item.completed_at,
        "version": item.version,
    }


class WorkoutService:
    def __init__(
        self,
        repository: SqlAlchemyWorkoutRepository,
        training: SqlAlchemyTrainingRepository,
        confirmations: SqlAlchemyConfirmationRepository | None = None,
    ) -> None:
        self.repository = repository
        self.training = training
        self.confirmations = confirmations

    async def create_workout(self, user_id: UUID, body: WorkoutCreateRequest) -> WorkoutAggregate:
        if await self.repository.get_active(user_id):
            raise WorkoutConflictError("An unfinished workout already exists")
        day_snapshot: dict | None = None
        calendar_event = None
        plan_day_id = body.plan_day_id
        if body.calendar_event_id:
            calendar_event = await self.training.get_calendar_event(user_id, body.calendar_event_id)
            if calendar_event is None:
                raise WorkoutNotFoundError("Calendar event not found")
            if calendar_event.status not in {"planned", "missed"}:
                raise WorkoutConflictError("Calendar event cannot be started in its current state")
            plan_day_id = calendar_event.plan_day_id
            if calendar_event.actual_workout_id:
                raise WorkoutConflictError("Calendar event already has a workout")
            if calendar_event.content_snapshot:
                day_snapshot = deepcopy(calendar_event.content_snapshot)
            elif calendar_event.plan_version_id:
                version = await self.training.get_plan_version(calendar_event.plan_version_id)
                day_snapshot = self._find_day(version, plan_day_id)
            if day_snapshot is None:
                raise WorkoutNotFoundError("Calendar event plan snapshot not found")
        elif plan_day_id:
            version = await self.training.get_active_plan(user_id)
            day_snapshot = self._find_day(version, plan_day_id)
            if day_snapshot is None:
                raise WorkoutNotFoundError("Active plan day not found")
        workout = Workout(
            user_id=user_id,
            calendar_event_id=body.calendar_event_id,
            plan_day_id=plan_day_id,
            started_at=body.started_at,
            pre_check=body.pre_check.model_dump(mode="json") if body.pre_check else {},
        )
        items: list[WorkoutExercise] = []
        for planned in (day_snapshot or {}).get("exercises", []):
            exercise_id = UUID(str(planned["exercise_id"]))
            exercise = await self.repository.get_exercise(user_id, exercise_id)
            items.append(
                WorkoutExercise(
                    workout_id=workout.id,
                    exercise_id=exercise_id if exercise else None,
                    original_exercise_id=exercise_id,
                    name_snapshot=exercise.name_zh if exercise else "已删除动作",
                    target_snapshot={
                        "sets": planned["target_sets"],
                        "rep_min": planned["rep_min"],
                        "rep_max": planned["rep_max"],
                        "target_load_kg": planned.get("target_load_kg"),
                        "target_rir": planned.get("target_rir"),
                        "rest_seconds": planned.get("rest_seconds"),
                    },
                    order_no=int(planned["order_no"]),
                )
            )
        await self.repository.add_workout(workout, items)
        if calendar_event:
            calendar_event.actual_workout_id = workout.id
            await self.repository.session.flush()
        return WorkoutAggregate(workout, items, {item.id: [] for item in items})

    async def get_aggregate(self, user_id: UUID, workout_id: UUID) -> WorkoutAggregate:
        aggregate = await self.repository.get_aggregate(user_id, workout_id)
        if aggregate is None:
            raise WorkoutNotFoundError("Workout not found")
        return aggregate

    async def get_active(self, user_id: UUID) -> WorkoutAggregate:
        workout = await self.repository.get_active(user_id)
        if workout is None:
            raise WorkoutNotFoundError("No active workout")
        return await self.get_aggregate(user_id, workout.id)

    async def create_set(
        self, user_id: UUID, workout_id: UUID, body: WorkoutSetCreateRequest
    ) -> WorkoutSet:
        workout = await self.repository.get_workout(user_id, workout_id, lock=True)
        if workout is None:
            raise WorkoutNotFoundError("Workout not found")
        if workout.status != "in_progress":
            raise WorkoutConflictError("Workout is already finished", workout.version)
        if body.completed_at < workout.started_at:
            raise WorkoutConflictError("completed_at cannot precede workout start", workout.version)
        existing = await self.repository.get_set_by_client_id(workout_id, body.client_generated_id)
        if existing:
            return existing
        duplicate_index = await self.repository.get_set_by_index(
            body.workout_exercise_id, body.set_index
        )
        if duplicate_index:
            raise WorkoutConflictError("Set index already exists", workout.version)
        exercise = await self.repository.get_workout_exercise(workout_id, body.workout_exercise_id)
        if exercise is None:
            raise WorkoutNotFoundError("Workout exercise not found")
        item = WorkoutSet(
            workout_id=workout_id,
            workout_exercise_id=body.workout_exercise_id,
            **body.model_dump(exclude={"workout_exercise_id"}),
        )
        await self.repository.add_set(item)
        workout.version += 1
        await self.repository.session.flush()
        return item

    async def update_set(
        self,
        user_id: UUID,
        workout_id: UUID,
        set_id: UUID,
        body: WorkoutSetUpdateRequest,
    ) -> WorkoutSet:
        workout = await self.repository.get_workout(user_id, workout_id)
        if workout is None:
            raise WorkoutNotFoundError("Workout not found")
        item = await self.repository.get_set(workout_id, set_id, lock=True)
        if item is None:
            raise WorkoutNotFoundError("Workout set not found")
        if item.version != body.expected_version:
            raise WorkoutConflictError("Workout set was modified", item.version)
        fields = body.model_fields_set - {"reason", "expected_version"}
        old_values = {name: getattr(item, name) for name in fields}
        for name in fields:
            setattr(item, name, getattr(body, name))
        item.version += 1
        new_values = {name: getattr(item, name) for name in fields}
        await self.repository.add_set_revision(
            WorkoutSetRevision(
                set_id=item.id,
                old_values=self._json_values(old_values),
                new_values=self._json_values(new_values),
                reason=body.reason,
            )
        )
        return item

    async def replace_exercise(
        self,
        user_id: UUID,
        workout_id: UUID,
        item_id: UUID,
        body: WorkoutExerciseReplaceRequest,
    ) -> WorkoutAggregate:
        workout = await self.repository.get_workout(user_id, workout_id, lock=True)
        if workout is None:
            raise WorkoutNotFoundError("Workout not found")
        if workout.version != body.expected_workout_version:
            raise WorkoutConflictError("Workout was modified", workout.version)
        item = await self.repository.get_workout_exercise(workout_id, item_id, lock=True)
        replacement = await self.repository.get_exercise(user_id, body.replacement_exercise_id)
        if item is None or replacement is None:
            raise WorkoutNotFoundError("Workout exercise or replacement not found")
        history = list(item.replacement_history)
        history.append(
            {
                "from_exercise_id": str(item.exercise_id) if item.exercise_id else None,
                "from_name": item.name_snapshot,
                "to_exercise_id": str(replacement.id),
                "to_name": replacement.name_zh,
                "reason": body.reason,
                "replaced_at": datetime.now(UTC).isoformat(),
            }
        )
        item.replacement_history = history
        item.exercise_id = replacement.id
        item.name_snapshot = replacement.name_zh
        workout.version += 1
        await self.repository.session.flush()
        return await self.get_aggregate(user_id, workout_id)

    async def finish_workout(
        self, user_id: UUID, workout_id: UUID, body: WorkoutFinishRequest
    ) -> dict:
        workout = await self.repository.get_workout(user_id, workout_id, lock=True)
        if workout is None:
            raise WorkoutNotFoundError("Workout not found")
        if workout.status != "in_progress" or workout.version != body.expected_version:
            raise WorkoutConflictError("Workout was modified or finished", workout.version)
        if body.ended_at < workout.started_at:
            raise WorkoutConflictError("ended_at cannot precede started_at", workout.version)
        workout.ended_at = body.ended_at
        workout.status = "interrupted" if body.interruption_reason else "completed"
        workout.overall_difficulty = body.overall_difficulty
        workout.fatigue = body.fatigue
        workout.pain = body.pain
        workout.interruption_reason = body.interruption_reason
        workout.version += 1
        sets = await self.repository.list_sets(workout_id)
        total_volume = sum((item.weight_kg * item.reps for item in sets), Decimal("0"))
        working_set_count = sum("warmup" not in item.tags for item in sets)
        aggregate = await self.get_aggregate(user_id, workout_id)
        target_sets = sum(int(item.target_snapshot.get("sets", 0)) for item in aggregate.exercises)
        adherence = (
            min(Decimal(working_set_count) / Decimal(target_sets), Decimal("1"))
            if target_sets
            else Decimal("0")
        )
        records: list[PersonalRecord] = []
        for exercise in aggregate.exercises:
            working_sets = [
                item
                for item in aggregate.sets_by_exercise.get(exercise.id, [])
                if "warmup" not in item.tags
            ]
            if exercise.exercise_id is None or not working_sets:
                continue
            candidates = {
                "max_weight": max(working_sets, key=lambda item: (item.weight_kg, item.reps)),
                "max_reps": max(working_sets, key=lambda item: (item.reps, item.weight_kg)),
            }
            for record_type, candidate in candidates.items():
                value = (
                    candidate.weight_kg
                    if record_type == "max_weight"
                    else Decimal(candidate.reps)
                )
                previous = await self.repository.best_record(
                    user_id, exercise.exercise_id, record_type
                )
                if previous is None or value > previous:
                    records.append(
                        PersonalRecord(
                            user_id=user_id,
                            exercise_id=exercise.exercise_id,
                            exercise_name_snapshot=exercise.name_snapshot,
                            record_type=record_type,
                            value=value,
                            occurred_at=candidate.completed_at,
                            workout_id=workout.id,
                            set_id=candidate.id,
                        )
                    )
        await self.repository.add_records(records)
        if workout.calendar_event_id:
            event = await self.training.get_calendar_event(
                user_id, workout.calendar_event_id, lock=True
            )
            if event:
                event.status = "completed"
        await self.repository.session.flush()
        return {
            "workout_id": workout.id,
            "duration_seconds": int((body.ended_at - workout.started_at).total_seconds()),
            "completed_sets": len(sets),
            "total_volume_kg": total_volume,
            "prs": [
                {
                    "exercise_id": str(item.exercise_id),
                    "record_type": item.record_type,
                    "value": str(item.value),
                }
                for item in records
            ],
            "pain_flags": body.pain,
            "plan_adherence": adherence.quantize(Decimal("0.01")),
        }

    async def create_progression_draft(
        self, user_id: UUID, workout_id: UUID, body: ProgressionDraftCreateRequest
    ) -> ProgressionDraft:
        aggregate = await self.get_aggregate(user_id, workout_id)
        if aggregate.workout.status == "in_progress":
            raise WorkoutConflictError("Finish the workout before requesting progression")
        selected = set(body.exercise_ids or [])
        suggestions: list[dict] = []
        for exercise in aggregate.exercises:
            if exercise.exercise_id is None or (selected and exercise.exercise_id not in selected):
                continue
            sets = [
                item
                for item in aggregate.sets_by_exercise.get(exercise.id, [])
                if "warmup" not in item.tags
            ]
            if not sets:
                continue
            target = exercise.target_snapshot
            current_weight = max((item.weight_kg for item in sets), default=Decimal("0"))
            all_completed = len(sets) >= int(target.get("sets", 0))
            rir_values = [item.rir for item in sets if item.rir is not None]
            has_pain = bool(aggregate.workout.pain)
            was_interrupted = aggregate.workout.status == "interrupted"
            can_increase = (
                all_completed
                and bool(rir_values)
                and min(rir_values) >= 2
                and not has_pain
                and not was_interrupted
            )
            proposed = current_weight + Decimal("2.500") if can_increase else current_weight
            evidence = [f"本次完成 {len(sets)} 组"]
            warnings = []
            if rir_values:
                evidence.append(f"最低 RIR 为 {min(rir_values)}")
            else:
                warnings.append("缺少 RIR，使用保守建议")
            if has_pain:
                warnings.append("本次记录了疼痛，暂停加重并优先评估疼痛")
            if was_interrupted:
                warnings.append("本次训练中断，不据此增加训练负荷")
            suggestions.append(
                {
                    "exercise_id": str(exercise.exercise_id),
                    "current_target": {
                        "weight_kg": str(current_weight),
                        "reps": target.get("rep_min"),
                    },
                    "proposed_target": {"weight_kg": str(proposed), "reps": target.get("rep_min")},
                    "evidence": evidence,
                    "warnings": warnings,
                }
            )
        draft = ProgressionDraft(user_id=user_id, workout_id=workout_id, suggestions=suggestions)
        return await self.repository.add_progression_draft(draft)

    async def submit_progression(
        self, user_id: UUID, workout_id: UUID, draft_id: UUID, expected_version: int
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        draft = await self.repository.get_progression_draft(
            user_id, workout_id, draft_id, lock=True
        )
        if draft is None:
            raise WorkoutNotFoundError("Progression draft not found")
        if draft.version != expected_version or draft.status != "editing":
            raise WorkoutConflictError("Progression draft was modified", draft.version)
        draft.status = "submitted"
        draft.version += 1
        active_plan = await self.training.get_active_plan(user_id)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="training_progression_apply",
                before=None,
                after={
                    "draft_id": str(draft.id),
                    "draft_version": draft.version,
                    "base_plan_version_id": str(active_plan.id) if active_plan else None,
                },
                reason="用户提交下一次训练进阶建议",
                impact="确认后生成新的训练计划版本，历史训练不变",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def apply_progression(
        self,
        user_id: UUID,
        draft_id: UUID,
        draft_version: int,
        base_plan_version_id: UUID | None,
    ) -> dict:
        draft = await self.repository.get_progression_draft_by_id(user_id, draft_id, lock=True)
        if draft is None:
            raise WorkoutConflictError("Progression draft changed before approval")
        if draft.version != draft_version or draft.status != "submitted":
            raise WorkoutConflictError("Progression draft changed before approval")
        current = await self.training.get_active_plan(user_id)
        if current is None:
            raise WorkoutConflictError("No active plan to update")
        if current.id != base_plan_version_id:
            raise WorkoutConflictError("Active training plan changed before approval")
        days = deepcopy(current.days)
        proposals = {item["exercise_id"]: item["proposed_target"] for item in draft.suggestions}
        for day in days:
            for item in day.get("exercises", []):
                proposed = proposals.get(str(item.get("exercise_id")))
                if proposed:
                    item["target_load_kg"] = proposed["weight_kg"]
                    item["rep_min"] = proposed["reps"]
                    item["rep_max"] = max(
                        int(item.get("rep_max", proposed["reps"])), proposed["reps"]
                    )
        current.status = "superseded"
        await self.training.session.flush()
        version = TrainingPlanVersion(
            plan_id=current.plan_id,
            user_id=user_id,
            name=current.name,
            weekly_frequency=current.weekly_frequency,
            days=days,
            version=current.version + 1,
            status="active",
            activated_at=datetime.now(UTC),
        )
        await self.training.add_plan_version(version)
        future_events = await self.training.list_future_plan_events(
            user_id, current.id, date.today()
        )
        days_by_id = {str(day.get("id")): day for day in days}
        for event in future_events:
            event.plan_version_id = version.id
            event.content_snapshot = deepcopy(days_by_id.get(str(event.plan_day_id)))
        await self.training.session.flush()
        return {"resource_id": str(current.plan_id), "resource_version": version.version}

    @staticmethod
    def _find_day(version: TrainingPlanVersion | None, plan_day_id: UUID | None) -> dict | None:
        if version is None or plan_day_id is None:
            return None
        return next((day for day in version.days if str(day.get("id")) == str(plan_day_id)), None)

    @staticmethod
    def _json_values(values: dict) -> dict:
        return {
            key: str(value) if isinstance(value, (Decimal, UUID, datetime)) else value
            for key, value in values.items()
        }
