from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nxtrep_backend.db.models import (
    CalendarEvent,
    CalendarRescheduleDraft,
    Confirmation,
    TrainingPlanDraft,
    TrainingPlanVersion,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.training import (
    CompressionDraftCreateRequest,
    PlanDayInput,
    PlanDraftCreateRequest,
    PlanDraftUpdateRequest,
    RescheduleDraftCreateRequest,
    SubstitutionDraftCreateRequest,
)


class TrainingNotFoundError(RuntimeError):
    pass


class TrainingConflictError(RuntimeError):
    def __init__(self, message: str, current_version: int | None = None) -> None:
        super().__init__(message)
        self.current_version = current_version


class TrainingValidationError(RuntimeError):
    def __init__(self, errors: list[dict]) -> None:
        super().__init__("Training plan is invalid")
        self.errors = errors


def _snapshot_days(days: list[PlanDayInput] | list[dict]) -> list[dict]:
    snapshots: list[dict] = []
    for raw_day in days:
        day = (
            raw_day.model_dump(mode="json") if isinstance(raw_day, PlanDayInput) else dict(raw_day)
        )
        day.setdefault("id", str(uuid4()))
        exercises = []
        for raw_item in day.get("exercises", []):
            item = dict(raw_item)
            item.setdefault("id", str(uuid4()))
            exercises.append(item)
        day["exercises"] = exercises
        snapshots.append(day)
    return snapshots


def draft_payload(draft: TrainingPlanDraft) -> dict:
    return {
        "id": draft.id,
        "name": draft.name,
        "status": draft.status,
        "version": draft.version,
        "weekly_frequency": draft.weekly_frequency,
        "days": draft.days,
        "validation_errors": draft.validation_errors,
        "validation_warnings": draft.validation_warnings,
    }


class TrainingService:
    def __init__(
        self,
        repository: SqlAlchemyTrainingRepository,
        confirmations: SqlAlchemyConfirmationRepository | None = None,
    ) -> None:
        self.repository = repository
        self.confirmations = confirmations

    async def get_active_plan(
        self,
        *,
        user_id: UUID,
    ) -> TrainingPlanVersion | None:
        """Return the user's active immutable plan version."""
        return await self.repository.get_active_plan(user_id)

    async def list_calendar(
        self,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[CalendarEvent]:
        """Return calendar events in an inclusive date range."""
        if start_date > end_date:
            raise ValueError("start_date must not exceed end_date")
        return await self.repository.list_calendar(user_id, start_date, end_date)

    async def create_manual_calendar_event(
        self,
        *,
        user_id: UUID,
        scheduled_date: date,
        title: str,
        estimated_minutes: int,
        exercises: list[dict],
    ) -> CalendarEvent:
        existing = await self.repository.get_event_on_date(user_id, scheduled_date)
        if existing is not None:
            raise TrainingConflictError("Target date already has a planned workout")
        snapshot = {
            "id": str(uuid4()),
            "day_index": 1,
            "name": title,
            "estimated_minutes": estimated_minutes,
            "exercises": exercises,
        }
        return await self.repository.add_calendar_event(
            CalendarEvent(
                user_id=user_id,
                scheduled_date=scheduled_date,
                title=title,
                estimated_minutes=estimated_minutes,
                content_snapshot=snapshot,
            )
        )

    async def create_manual_draft(
        self, user_id: UUID, body: PlanDraftCreateRequest
    ) -> TrainingPlanDraft:
        draft = TrainingPlanDraft(
            user_id=user_id,
            name=body.name.strip(),
            weekly_frequency=body.weekly_frequency,
            days=_snapshot_days(body.days),
            source="manual",
        )
        await self.repository.add_draft(draft)
        await self.validate_draft(user_id, draft)
        return draft

    async def create_from_template(
        self, user_id: UUID, template_id: UUID, name: str | None
    ) -> TrainingPlanDraft:
        template = await self.repository.get_template(template_id)
        if template is None:
            raise TrainingNotFoundError("Training template not found")
        draft = TrainingPlanDraft(
            user_id=user_id,
            name=(name or template.name).strip(),
            weekly_frequency=template.days_per_week,
            days=_snapshot_days(template.days),
            source="official_template",
        )
        await self.repository.add_draft(draft)
        await self.validate_draft(user_id, draft)
        return draft

    async def create_suggested_draft(
        self,
        *,
        user_id: UUID,
        source: str,
        template_id: UUID | None = None,
        name: str | None = None,
        goal_type: str | None = None,
        days_per_week: int | None = None,
        equipment: str | None = None,
    ) -> TrainingPlanDraft:
        if template_id is not None:
            template = await self.repository.get_template(template_id)
            templates = [template] if template is not None else []
        else:
            templates = await self.repository.list_templates(
                goal_type=goal_type,
                days_per_week=days_per_week,
                equipment=equipment,
            )
        if not templates:
            raise TrainingNotFoundError("No matching training template found")
        template = templates[0]
        draft = TrainingPlanDraft(
            user_id=user_id,
            name=(name or template.name).strip(),
            weekly_frequency=template.days_per_week,
            days=_snapshot_days(template.days),
            source=source,
        )
        await self.repository.add_draft(draft)
        await self.validate_draft(user_id, draft)
        return draft

    async def get_draft(self, user_id: UUID, draft_id: UUID) -> TrainingPlanDraft:
        draft = await self.repository.get_draft(user_id, draft_id)
        if draft is None:
            raise TrainingNotFoundError("Training plan draft not found")
        return draft

    async def delete_draft(
        self,
        *,
        user_id: UUID,
        draft_id: UUID,
        expected_version: int,
    ) -> None:
        draft = await self.repository.get_draft(user_id, draft_id, lock=True)
        if draft is None:
            raise TrainingNotFoundError("Training plan draft not found")
        if draft.version != expected_version:
            raise TrainingConflictError("Training plan draft was modified", draft.version)
        if draft.status != "editing":
            raise TrainingConflictError("Submitted training plan draft cannot be deleted")
        await self.repository.delete_draft(draft)

    async def create_revision_draft(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
        base_version: int,
        name: str | None,
    ) -> TrainingPlanDraft:
        version = await self.repository.get_plan_version_for_user(
            user_id=user_id,
            plan_id=plan_id,
            version=base_version,
        )
        if version is None:
            raise TrainingNotFoundError("Training plan version not found")
        draft = TrainingPlanDraft(
            user_id=user_id,
            name=name or version.name,
            weekly_frequency=version.weekly_frequency,
            days=deepcopy(version.days),
            source="revision",
        )
        return await self.repository.add_draft(draft)

    async def create_archive_confirmation(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
        expected_version: int,
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        latest = await self.repository.get_latest_plan(
            user_id=user_id,
            plan_id=plan_id,
        )
        if latest is None:
            raise TrainingNotFoundError("Training plan not found")
        if latest.version != expected_version or latest.status != "active":
            raise TrainingConflictError("Training plan cannot be archived", latest.version)
        confirmation = Confirmation(
            user_id=user_id,
            operation_type="training_plan_archive",
            before={
                "plan_id": str(plan_id),
                "version": latest.version,
                "status": latest.status,
            },
            after={
                "plan_id": str(plan_id),
                "version_id": str(latest.id),
                "version": latest.version,
                "status": "archived",
            },
            reason="用户请求归档当前训练计划",
            impact="停止使用该计划并删除未来尚未执行的计划日历事件，历史训练保留",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        return await self.confirmations.add_confirmation(confirmation)

    async def archive_plan(
        self,
        *,
        user_id: UUID,
        plan_id: UUID,
        version_id: UUID,
        version: int,
    ) -> dict:
        item = await self.repository.get_plan_version_for_user(
            user_id=user_id,
            plan_id=plan_id,
            version=version,
            lock=True,
        )
        if item is None or item.id != version_id or item.status != "active":
            raise TrainingConflictError("Training plan changed before approval")
        item.status = "archived"
        await self.repository.delete_future_planned_events(user_id, date.today())
        await self.repository.session.flush()
        return {"resource_id": str(plan_id), "resource_version": version}

    async def update_draft(
        self, user_id: UUID, draft_id: UUID, body: PlanDraftUpdateRequest
    ) -> TrainingPlanDraft:
        draft = await self.repository.get_draft(user_id, draft_id, lock=True)
        if draft is None:
            raise TrainingNotFoundError("Training plan draft not found")
        if draft.status != "editing":
            raise TrainingConflictError("Submitted plan drafts are read-only", draft.version)
        if draft.version != body.expected_version:
            raise TrainingConflictError("Training plan draft was modified", draft.version)
        supplied = body.model_fields_set
        if "name" in supplied:
            draft.name = body.name or draft.name
        if "weekly_frequency" in supplied:
            draft.weekly_frequency = body.weekly_frequency or draft.weekly_frequency
        if "days" in supplied and body.days is not None:
            draft.days = _snapshot_days(body.days)
        if draft.weekly_frequency != len(draft.days):
            raise TrainingValidationError(
                [{"field": "weekly_frequency", "message": "must equal number of days"}]
            )
        draft.version += 1
        await self.repository.session.flush()
        await self.validate_draft(user_id, draft)
        return draft

    async def validate_draft(
        self, user_id: UUID, draft: TrainingPlanDraft
    ) -> tuple[list[dict], list[dict], int]:
        errors: list[dict] = []
        warnings: list[dict] = []
        ids: set[UUID] = set()
        estimated = 0
        for day in draft.days:
            estimated += int(day.get("estimated_minutes", 0))
            if not day.get("exercises"):
                warnings.append(
                    {"field": f"days.{day.get('day_index')}", "message": "training day is empty"}
                )
            for item in day.get("exercises", []):
                try:
                    ids.add(UUID(str(item["exercise_id"])))
                except (KeyError, ValueError):
                    errors.append({"field": "exercise_id", "message": "invalid exercise id"})
        visible = await self.repository.visible_exercise_ids(user_id, ids)
        for missing in sorted(ids - visible, key=str):
            errors.append({"field": "exercise_id", "message": f"exercise {missing} is unavailable"})
        draft.validation_errors = errors
        draft.validation_warnings = warnings
        await self.repository.session.flush()
        return errors, warnings, estimated

    async def submit_draft(
        self, user_id: UUID, draft_id: UUID, expected_version: int
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        draft = await self.repository.get_draft(user_id, draft_id, lock=True)
        if draft is None:
            raise TrainingNotFoundError("Training plan draft not found")
        if draft.version != expected_version:
            raise TrainingConflictError("Training plan draft was modified", draft.version)
        errors, _, _ = await self.validate_draft(user_id, draft)
        if errors:
            raise TrainingValidationError(errors)
        if draft.status != "editing":
            raise TrainingConflictError("Training plan draft was already submitted", draft.version)
        draft.status = "submitted"
        draft.version += 1
        active_plan = await self.repository.get_active_plan(user_id)
        confirmation = Confirmation(
            user_id=user_id,
            operation_type="training_plan_activate",
            before=None,
            after={
                "plan_draft_id": str(draft.id),
                "draft_version": draft.version,
                "base_plan_version_id": str(active_plan.id) if active_plan else None,
            },
            reason="用户提交新的训练计划",
            impact="未来日历使用新计划，历史训练不变",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        return await self.confirmations.add_confirmation(confirmation)

    async def activate_draft(
        self,
        user_id: UUID,
        draft_id: UUID,
        draft_version: int,
        base_plan_version_id: UUID | None,
    ) -> dict:
        draft = await self.repository.get_draft(user_id, draft_id, lock=True)
        if draft is None or draft.version != draft_version or draft.status != "submitted":
            raise TrainingConflictError("Training plan draft changed before approval")
        errors, _, _ = await self.validate_draft(user_id, draft)
        if errors:
            raise TrainingValidationError(errors)
        current = await self.repository.get_active_plan(user_id)
        if (current.id if current else None) != base_plan_version_id:
            raise TrainingConflictError("Active training plan changed before approval")
        if current:
            current.status = "superseded"
            plan_id = current.plan_id
            version_number = current.version + 1
            await self.repository.session.flush()
        else:
            plan_id = uuid4()
            version_number = 1
        activated_at = datetime.now(UTC)
        version = TrainingPlanVersion(
            plan_id=plan_id,
            user_id=user_id,
            source_draft_id=draft.id,
            name=draft.name,
            weekly_frequency=draft.weekly_frequency,
            days=draft.days,
            version=version_number,
            status="active",
            activated_at=activated_at,
        )
        await self.repository.add_plan_version(version)
        start = date.today()
        await self.repository.delete_future_planned_events(user_id, start)
        events: list[CalendarEvent] = []
        for week in range(4):
            for day in draft.days:
                events.append(
                    CalendarEvent(
                        user_id=user_id,
                        scheduled_date=start + timedelta(days=week * 7 + int(day["day_index"]) - 1),
                        plan_version_id=version.id,
                        plan_day_id=UUID(str(day["id"])),
                        title=str(day["name"]),
                        estimated_minutes=int(day["estimated_minutes"]),
                        content_snapshot=deepcopy(day),
                    )
                )
        await self.repository.add_calendar_events(events)
        return {"resource_id": str(plan_id), "resource_version": version_number}

    async def create_reschedule_draft(
        self, user_id: UUID, body: RescheduleDraftCreateRequest
    ) -> CalendarRescheduleDraft:
        missed = await self.repository.get_calendar_event(user_id, body.missed_event_id)
        if missed is None:
            raise TrainingNotFoundError("Calendar event not found")
        if missed.status not in {"planned", "missed"} or missed.actual_workout_id is not None:
            raise TrainingConflictError("Only uncompleted calendar events can be rescheduled")
        before = [self._event_snapshot(missed)]
        after: list[dict] = []
        duration_change = 0
        volume_change = Decimal("0")
        warnings: list[str] = []
        if body.strategy == "skip":
            after = [{**before[0], "status": "skipped"}]
            duration_change = -missed.estimated_minutes
        elif body.strategy == "shift":
            target = await self.repository.get_event_on_date(user_id, body.target_date)
            if target is not None and target.id != missed.id:
                raise TrainingValidationError(
                    [{"field": "target_date", "message": "target date already has a workout"}]
                )
            after = [{**before[0], "scheduled_date": body.target_date.isoformat()}]
        else:
            target = await self.repository.get_event_on_date(user_id, body.target_date)
            if target is None:
                raise TrainingValidationError(
                    [{"field": "target_date", "message": "merge target event not found"}]
                )
            before.append(self._event_snapshot(target))
            missed_day = await self._event_day_snapshot(missed)
            target_day = await self._event_day_snapshot(target)
            if missed_day is None or target_day is None:
                raise TrainingValidationError(
                    [{"field": "missed_event_id", "message": "plan snapshot is unavailable"}]
                )
            target_ids = {str(item.get("exercise_id")) for item in target_day.get("exercises", [])}
            candidate = next(
                (
                    deepcopy(item)
                    for item in missed_day.get("exercises", [])
                    if str(item.get("exercise_id")) not in target_ids
                ),
                None,
            )
            if candidate is None:
                raise TrainingValidationError(
                    [{"field": "strategy", "message": "no non-duplicate exercise to merge"}]
                )
            merged_day = deepcopy(target_day)
            merged_exercises = list(merged_day.get("exercises", []))
            candidate["id"] = str(uuid4())
            candidate["order_no"] = len(merged_exercises) + 1
            merged_exercises.append(candidate)
            merged_day["exercises"] = merged_exercises
            missed_volume = self._day_volume({"exercises": [candidate]})
            target_volume = self._day_volume(target_day)
            added_ratio = missed_volume / target_volume if target_volume > 0 else Decimal("1")
            added_minutes = max(
                1,
                int((Decimal(missed.estimated_minutes) * added_ratio).quantize(Decimal("1"))),
            )
            merged_minutes = target.estimated_minutes + added_minutes
            merged_day["estimated_minutes"] = merged_minutes
            after = [
                {
                    **self._event_snapshot(target),
                    "title": f"{target.title} + {missed.title}",
                    "estimated_minutes": merged_minutes,
                    "content_snapshot": merged_day,
                    "added_exercises": [candidate],
                }
            ]
            if merged_minutes > 90:
                warnings.append("合并后预计总时长超过 90 分钟")
            volume_change = (
                Decimal("100")
                if target_volume <= 0 and missed_volume > 0
                else (
                    missed_volume / target_volume * Decimal("100")
                    if target_volume > 0
                    else Decimal("0")
                )
            )
            if volume_change > Decimal("30"):
                warnings.append("合并后预计训练量增加超过 30%")
            duration_change = added_minutes
        draft = CalendarRescheduleDraft(
            user_id=user_id,
            missed_event_id=missed.id,
            strategy=body.strategy,
            target_date=body.target_date,
            reason=body.reason,
            before_events=before,
            after_events=after,
            duration_change_minutes=duration_change,
            volume_change_percent=volume_change.quantize(Decimal("0.01")),
            warnings=warnings,
        )
        return await self.repository.add_reschedule_draft(draft)

    async def submit_reschedule(
        self, user_id: UUID, draft_id: UUID, expected_version: int
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        draft = await self.repository.get_reschedule_draft(user_id, draft_id, lock=True)
        if draft is None:
            raise TrainingNotFoundError("Reschedule draft not found")
        if draft.version != expected_version or draft.status != "editing":
            raise TrainingConflictError("Reschedule draft was modified", draft.version)
        if draft.warnings:
            raise TrainingValidationError(
                [{"field": "strategy", "message": w} for w in draft.warnings]
            )
        draft.status = "submitted"
        draft.version += 1
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="calendar_reschedule",
                before={"events": draft.before_events},
                after={"draft_id": str(draft.id), "draft_version": draft.version},
                reason=draft.reason or "用户提交漏练调整",
                impact="确认后将调整未来日历，历史训练不变",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def create_compression_draft(
        self, user_id: UUID, body: CompressionDraftCreateRequest
    ) -> CalendarRescheduleDraft:
        event = await self.repository.get_calendar_event(user_id, body.event_id)
        if event is None:
            raise TrainingNotFoundError("Calendar event not found")
        if event.status not in {"planned", "missed"} or event.actual_workout_id is not None:
            raise TrainingConflictError("Only uncompleted calendar events can be compressed")
        if body.target_minutes >= event.estimated_minutes:
            raise TrainingValidationError(
                [{"field": "target_minutes", "message": "must be shorter than current duration"}]
            )
        day = await self._event_day_snapshot(event)
        if day is None or not day.get("exercises"):
            raise TrainingValidationError(
                [{"field": "event_id", "message": "event has no compressible plan snapshot"}]
            )
        original_volume = self._day_volume(day)
        ratio = Decimal(body.target_minutes) / Decimal(event.estimated_minutes)
        keep_count = max(1, round(len(day["exercises"]) * float(ratio)))
        compressed_day = deepcopy(day)
        compressed_day["exercises"] = deepcopy(day["exercises"][:keep_count])
        compressed_day["estimated_minutes"] = body.target_minutes
        compressed_volume = self._day_volume(compressed_day)
        volume_change = (
            (compressed_volume - original_volume) / original_volume * Decimal("100")
            if original_volume > 0
            else Decimal("0")
        )
        before = [self._event_snapshot(event)]
        after = [
            {
                **before[0],
                "estimated_minutes": body.target_minutes,
                "content_snapshot": compressed_day,
            }
        ]
        return await self.repository.add_reschedule_draft(
            CalendarRescheduleDraft(
                user_id=user_id,
                missed_event_id=event.id,
                strategy="compression",
                target_date=event.scheduled_date,
                reason=body.reason,
                before_events=before,
                after_events=after,
                duration_change_minutes=body.target_minutes - event.estimated_minutes,
                volume_change_percent=volume_change.quantize(Decimal("0.01")),
                warnings=[],
            )
        )

    async def create_substitution_draft(
        self, user_id: UUID, body: SubstitutionDraftCreateRequest
    ) -> CalendarRescheduleDraft:
        event = await self.repository.get_calendar_event(user_id, body.event_id)
        if event is None:
            raise TrainingNotFoundError("Calendar event not found")
        if event.status not in {"planned", "missed"} or event.actual_workout_id is not None:
            raise TrainingConflictError("Only uncompleted calendar events can be changed")
        if body.exercise_id == body.replacement_exercise_id:
            raise TrainingValidationError(
                [{"field": "replacement_exercise_id", "message": "must differ from exercise_id"}]
            )
        replacement = await self.repository.get_visible_exercise(
            user_id, body.replacement_exercise_id
        )
        if replacement is None:
            raise TrainingNotFoundError("Replacement exercise not found")
        day = await self._event_day_snapshot(event)
        if day is None:
            raise TrainingValidationError(
                [{"field": "event_id", "message": "event has no plan snapshot"}]
            )
        substituted = deepcopy(day)
        candidate = next(
            (
                item
                for item in substituted.get("exercises", [])
                if str(item.get("exercise_id")) == str(body.exercise_id)
            ),
            None,
        )
        if candidate is None:
            raise TrainingValidationError(
                [{"field": "exercise_id", "message": "exercise is not in this event"}]
            )
        candidate["original_exercise_id"] = str(body.exercise_id)
        candidate["exercise_id"] = str(replacement.id)
        candidate["name"] = replacement.name_zh
        candidate["substitution_reason"] = body.reason
        before = [self._event_snapshot(event)]
        after = [{**before[0], "content_snapshot": substituted}]
        return await self.repository.add_reschedule_draft(
            CalendarRescheduleDraft(
                user_id=user_id,
                missed_event_id=event.id,
                strategy="substitution",
                target_date=event.scheduled_date,
                reason=body.reason,
                before_events=before,
                after_events=after,
                duration_change_minutes=0,
                volume_change_percent=Decimal("0"),
                warnings=[],
            )
        )

    async def apply_reschedule(self, user_id: UUID, draft_id: UUID, draft_version: int) -> dict:
        draft = await self.repository.get_reschedule_draft(user_id, draft_id, lock=True)
        if draft is None or draft.version != draft_version or draft.status != "submitted":
            raise TrainingConflictError("Reschedule draft changed before approval")
        missed = await self.repository.get_calendar_event(user_id, draft.missed_event_id, lock=True)
        if missed is None:
            raise TrainingConflictError("Calendar event changed before approval")
        if missed.status not in {"planned", "missed"} or missed.actual_workout_id is not None:
            raise TrainingConflictError("Calendar event changed before approval")
        original_missed = draft.before_events[0]
        if (
            missed.scheduled_date.isoformat() != original_missed["scheduled_date"]
            or missed.status != original_missed["status"]
        ):
            raise TrainingConflictError("Calendar event changed before approval")
        if draft.strategy == "skip":
            missed.status = "skipped"
        elif draft.strategy == "shift":
            missed.scheduled_date = draft.target_date
            missed.status = "planned"
        elif draft.strategy == "merge":
            target = await self.repository.get_event_on_date(user_id, draft.target_date)
            if target is None:
                raise TrainingConflictError("Merge target changed before approval")
            original_target = draft.before_events[1]
            if (
                target.id != UUID(original_target["id"])
                or target.scheduled_date.isoformat() != original_target["scheduled_date"]
                or target.status != original_target["status"]
                or target.actual_workout_id is not None
            ):
                raise TrainingConflictError("Merge target changed before approval")
            target.title = str(draft.after_events[0]["title"])
            target.estimated_minutes = int(draft.after_events[0]["estimated_minutes"])
            target.content_snapshot = draft.after_events[0]["content_snapshot"]
            missed.status = "skipped"
        else:
            missed.estimated_minutes = int(draft.after_events[0]["estimated_minutes"])
            missed.content_snapshot = draft.after_events[0]["content_snapshot"]
            missed.status = "planned"
        await self.repository.session.flush()
        return {"resource_id": str(missed.id), "resource_version": draft.version}

    @staticmethod
    def _event_snapshot(event: CalendarEvent) -> dict:
        return {
            "id": str(event.id),
            "scheduled_date": event.scheduled_date.isoformat(),
            "status": event.status,
            "plan_day_id": str(event.plan_day_id) if event.plan_day_id else None,
            "title": event.title,
            "estimated_minutes": event.estimated_minutes,
        }

    async def _event_volume(self, event: CalendarEvent) -> Decimal:
        day = await self._event_day_snapshot(event)
        return self._day_volume(day)

    async def _event_day_snapshot(self, event: CalendarEvent) -> dict | None:
        if event.content_snapshot:
            return deepcopy(event.content_snapshot)
        if event.plan_version_id is None or event.plan_day_id is None:
            return None
        version = await self.repository.get_plan_version(event.plan_version_id)
        return next(
            (
                item
                for item in (version.days if version else [])
                if str(item.get("id")) == str(event.plan_day_id)
            ),
            None,
        )

    @staticmethod
    def _day_volume(day: dict | None) -> Decimal:
        volume = Decimal("0")
        for item in (day or {}).get("exercises", []):
            sets = Decimal(str(item.get("target_sets", 0)))
            reps = Decimal(str(item.get("rep_min", 0)))
            load = Decimal(str(item.get("target_load_kg") or 1))
            volume += sets * reps * load
        return volume
