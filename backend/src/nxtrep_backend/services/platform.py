import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from nxtrep_backend.db.models import (
    AgentMemory,
    AppAlert,
    AppNotification,
    AuditEvent,
    BodyMeasurement,
    DeletionDraft,
    ExportJob,
    GeneratedReport,
    NotificationSetting,
    NutritionEntry,
    PushDevice,
    SyncChange,
    SyncConflict,
    SyncResource,
    User,
    Workout,
)
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.platform import SqlAlchemyPlatformRepository
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.schemas.platform import (
    DeletionConfirmRequest,
    NotificationSettingsUpdate,
    PushTokenCreateRequest,
    SyncConflictResolveRequest,
    SyncPushRequest,
)
from nxtrep_backend.services.body import BodyService


class PlatformNotFoundError(RuntimeError):
    pass


class PlatformConflictError(RuntimeError):
    pass


class PlatformService:
    def __init__(self, repository: SqlAlchemyPlatformRepository) -> None:
        self.repository = repository

    async def get_notification_settings(self, user_id: UUID) -> NotificationSetting:
        item = await self.repository.get_notification_settings(user_id)
        if item is None:
            item = await self.repository.add(NotificationSetting(user_id=user_id))
        return item

    async def update_notification_settings(
        self, user_id: UUID, body: NotificationSettingsUpdate
    ) -> NotificationSetting:
        item = await self.repository.get_notification_settings(user_id, lock=True)
        if item is None:
            if body.expected_version != 1:
                raise PlatformConflictError("Notification settings version conflict")
            item = await self.repository.add(NotificationSetting(user_id=user_id))
        elif item.version != body.expected_version:
            raise PlatformConflictError("Notification settings version conflict")
        for field in body.model_fields_set - {"expected_version"}:
            setattr(item, field, getattr(body, field))
        item.version += 1
        await self.repository.session.flush()
        await self.audit(user_id, "notification_settings.updated", "settings", str(user_id))
        return item

    async def mark_notification_read(self, user_id: UUID, item_id: UUID) -> AppNotification:
        item = await self.repository.get_notification(user_id, item_id, lock=True)
        if item is None:
            raise PlatformNotFoundError("Notification not found")
        item.read_at = item.read_at or datetime.now(UTC)
        await self.repository.session.flush()
        return item

    async def register_push_device(self, user_id: UUID, body: PushTokenCreateRequest) -> PushDevice:
        item = await self.repository.get_push_device(user_id, body.device_id, lock=True)
        token_hash = hashlib.sha256(body.token.encode()).hexdigest()
        if item is None:
            item = await self.repository.add(
                PushDevice(
                    user_id=user_id,
                    device_id=body.device_id,
                    platform=body.platform,
                    token_hash=token_hash,
                    token_last_four=body.token[-4:],
                )
            )
        else:
            item.platform = body.platform
            item.token_hash = token_hash
            item.token_last_four = body.token[-4:]
            item.revoked_at = None
            await self.repository.session.flush()
        await self.audit(user_id, "push_device.registered", "push_device", str(item.id))
        return item

    async def revoke_push_device(self, user_id: UUID, item_id: UUID) -> None:
        item = await self.repository.get_push_device_by_id(user_id, item_id, lock=True)
        if item is None:
            raise PlatformNotFoundError("Push device not found")
        item.revoked_at = datetime.now(UTC)
        await self.repository.session.flush()
        await self.audit(user_id, "push_device.revoked", "push_device", str(item.id))

    async def sync_push(self, user_id: UUID, body: SyncPushRequest) -> tuple[list[dict], int]:
        results = []
        for change in body.changes:
            current = await self.repository.get_sync_resource(
                user_id, change.resource_type, change.resource_key, lock=True
            )
            current_version = current.version if current else 0
            if current_version != change.base_version:
                conflict = await self.repository.add(
                    SyncConflict(
                        user_id=user_id,
                        resource_type=change.resource_type,
                        resource_key=change.resource_key,
                        client_payload=change.payload,
                        server_payload=current.payload if current else {},
                        client_version=change.base_version,
                        server_version=current_version,
                    )
                )
                results.append(
                    {
                        "resource_type": change.resource_type,
                        "resource_key": change.resource_key,
                        "status": "conflict",
                        "version": current_version,
                        "conflict_id": conflict.id,
                    }
                )
                continue
            next_version = current_version + 1
            if current is None:
                current = await self.repository.add(
                    SyncResource(
                        user_id=user_id,
                        resource_type=change.resource_type,
                        resource_key=change.resource_key,
                        payload=change.payload,
                        version=next_version,
                        deleted=change.operation == "delete",
                    )
                )
            else:
                current.payload = change.payload
                current.version = next_version
                current.deleted = change.operation == "delete"
            await self.repository.add(
                SyncChange(
                    user_id=user_id,
                    resource_type=change.resource_type,
                    resource_key=change.resource_key,
                    operation=change.operation,
                    version=next_version,
                    payload=None if change.operation == "delete" else change.payload,
                )
            )
            results.append(
                {
                    "resource_type": change.resource_type,
                    "resource_key": change.resource_key,
                    "status": "applied",
                    "version": next_version,
                }
            )
        await self.repository.session.flush()
        return results, await self.repository.latest_cursor(user_id)

    async def resolve_conflict(
        self, user_id: UUID, conflict_id: UUID, body: SyncConflictResolveRequest
    ) -> SyncConflict:
        conflict = await self.repository.get_conflict(user_id, conflict_id, lock=True)
        if conflict is None:
            raise PlatformNotFoundError("Sync conflict not found")
        if conflict.status != "open":
            raise PlatformConflictError("Sync conflict is already resolved")
        if body.resolution == "manual" and body.merged_payload is None:
            raise PlatformConflictError("merged_payload is required for manual resolution")
        if body.resolution != "server":
            current = await self.repository.get_sync_resource(
                user_id, conflict.resource_type, conflict.resource_key, lock=True
            )
            payload = (
                body.merged_payload if body.resolution == "manual" else conflict.client_payload
            )
            next_version = (current.version if current else 0) + 1
            if current is None:
                current = await self.repository.add(
                    SyncResource(
                        user_id=user_id,
                        resource_type=conflict.resource_type,
                        resource_key=conflict.resource_key,
                        payload=payload,
                        version=next_version,
                    )
                )
            else:
                current.payload = payload
                current.version = next_version
                current.deleted = False
            await self.repository.add(
                SyncChange(
                    user_id=user_id,
                    resource_type=conflict.resource_type,
                    resource_key=conflict.resource_key,
                    operation="upsert",
                    version=next_version,
                    payload=payload,
                )
            )
        conflict.status = "resolved"
        conflict.resolution = body.resolution
        conflict.resolved_at = datetime.now(UTC)
        await self.repository.session.flush()
        return conflict

    async def create_export(self, user_id: UUID, include: list[str]) -> ExportJob:
        job = await self.repository.add(ExportJob(user_id=user_id, status="processing"))
        payload: dict = {"generated_at": datetime.now(UTC).isoformat()}
        allowed = set(include)
        if "training" in allowed:
            payload["training"] = await self._rows(Workout, user_id)
        if "nutrition" in allowed:
            payload["nutrition"] = await self._rows(NutritionEntry, user_id)
        if "body" in allowed:
            payload["body"] = await self._rows(BodyMeasurement, user_id)
        if "memories" in allowed:
            payload["memories"] = await self._rows(AgentMemory, user_id)
        user = await self.repository.session.get(User, user_id)
        if "profile" in allowed and user is not None:
            payload["account"] = {"id": str(user.id), "username": user.username}
        job.payload = self._json(payload)
        job.status = "completed"
        job.expires_at = datetime.now(UTC) + timedelta(hours=24)
        await self.repository.session.flush()
        await self.audit(user_id, "export.created", "export", str(job.id))
        return job

    async def create_deletion_draft(self, user_id: UUID) -> DeletionDraft:
        counts = {}
        for name, model in (
            ("workouts", Workout),
            ("nutrition_entries", NutritionEntry),
            ("body_measurements", BodyMeasurement),
            ("memories", AgentMemory),
        ):
            counts[name] = int(
                await self.repository.session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )
                or 0
            )
        now = datetime.now(UTC)
        item = await self.repository.add(
            DeletionDraft(
                user_id=user_id,
                scope="account",
                preview={
                    "records": counts,
                    "effect": "账号将立即停用，数据进入 30 天恢复期后方可清除",
                },
                status="pending",
                expires_at=now + timedelta(hours=24),
                recovery_until=now + timedelta(days=30),
                version=1,
            )
        )
        await self.audit(user_id, "deletion.requested", "deletion_draft", str(item.id))
        return item

    async def confirm_deletion(
        self, user: User, draft_id: UUID, body: DeletionConfirmRequest
    ) -> DeletionDraft:
        item = await self.repository.get_deletion_draft(user.id, draft_id, lock=True)
        if item is None:
            raise PlatformNotFoundError("Deletion draft not found")
        if item.status != "pending" or item.version != body.expected_version:
            raise PlatformConflictError("Deletion draft changed")
        if item.expires_at <= datetime.now(UTC):
            item.status = "expired"
            raise PlatformConflictError("Deletion draft expired")
        item.status = "confirmed"
        item.version += 1
        user.status = "disabled"
        await SqlAlchemyUserRepository(self.repository.session).revoke_active_refresh_sessions(
            user_id=user.id, revoked_at=datetime.now(UTC)
        )
        await self.audit(user.id, "deletion.confirmed", "user", str(user.id))
        await self.repository.session.flush()
        return item

    async def generate_weekly_report(self, user_id: UUID, week_start: date) -> GeneratedReport:
        return await self.generate_report(
            user_id, "weekly", week_start, week_start + timedelta(days=6)
        )

    async def generate_report(
        self, user_id: UUID, report_type: str, period_start: date, period_end: date
    ) -> GeneratedReport:
        if period_start > period_end:
            raise PlatformConflictError("Report start date must not exceed end date")
        overview = await BodyService(SqlAlchemyBodyRepository(self.repository.session)).overview(
            user_id, period_start, period_end
        )
        missing = []
        if overview["training"]["workout_count"] == 0:
            missing.append("training")
        if overview["nutrition"]["record_completeness"] == "0.00":
            missing.append("nutrition")
        if overview["body"]["weight_end_kg"] is None:
            missing.append("body")
        recommendations = []
        if overview["training"]["workout_count"] < 2:
            recommendations.append("下周优先完成至少两次可持续的训练")
        if float(overview["nutrition"]["record_completeness"]) < 0.7:
            recommendations.append("提高饮食记录完整度后再调整热量目标")
        current = await self.repository.get_report_period(
            user_id, report_type, period_start, period_end, lock=True
        )
        if current is None:
            current = await self.repository.add(
                GeneratedReport(
                    user_id=user_id,
                    report_type=report_type,
                    period_start=period_start,
                    period_end=period_end,
                    facts=overview,
                    missing_data=missing,
                    recommendations=recommendations,
                    evidence=[],
                    version=1,
                )
            )
        else:
            current.facts = overview
            current.missing_data = missing
            current.recommendations = recommendations
            current.version += 1
        await self.repository.session.flush()
        return current

    async def refresh_alerts(self, user_id: UUID) -> None:
        end = date.today()
        start = end - timedelta(days=13)
        workouts, _, measurements, _, _ = await SqlAlchemyBodyRepository(
            self.repository.session
        ).progress_rows(user_id, start, end)
        weighted = [item for item in measurements if item.weight_kg is not None]
        if len(weighted) >= 3 and weighted[0].weight_kg:
            change = (weighted[-1].weight_kg - weighted[0].weight_kg) / weighted[0].weight_kg
            if (
                abs(change) >= Decimal("0.05")
                and await self.repository.get_open_alert_by_type(user_id, "rapid_weight_change")
                is None
            ):
                await self.repository.add(
                    AppAlert(
                        user_id=user_id,
                        alert_type="rapid_weight_change",
                        severity="warning",
                        title="近期体重变化较快",
                        message=(
                            "过去 14 天内至少三次测量显示体重变化超过 5%，"
                            "建议复核测量条件并关注恢复。"
                        ),
                        evidence=[
                            {"measurement_id": str(item.id), "weight_kg": str(item.weight_kg)}
                            for item in (weighted[0], weighted[-1])
                        ],
                    )
                )
        pain_workouts = [item for item in workouts if item.pain]
        if (
            len(pain_workouts) >= 2
            and await self.repository.get_open_alert_by_type(user_id, "repeated_pain") is None
        ):
            await self.repository.add(
                AppAlert(
                    user_id=user_id,
                    alert_type="repeated_pain",
                    severity="warning",
                    title="多次训练记录了疼痛",
                    message="近 14 天至少两次训练记录疼痛；建议降低负荷，必要时咨询专业人士。",
                    evidence=[{"workout_id": str(item.id)} for item in pain_workouts[-3:]],
                )
            )

    async def dismiss_alert(self, user_id: UUID, alert_id: UUID) -> AppAlert:
        item = await self.repository.get_alert(user_id, alert_id, lock=True)
        if item is None:
            raise PlatformNotFoundError("Alert not found")
        if item.status == "open":
            item.status = "dismissed"
            item.dismissed_at = datetime.now(UTC)
            await self.repository.session.flush()
        return item

    async def audit(
        self,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict | None = None,
    ) -> AuditEvent:
        return await self.repository.add(
            AuditEvent(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
            )
        )

    async def _rows(self, model, user_id: UUID) -> list[dict]:
        rows = list(
            await self.repository.session.scalars(select(model).where(model.user_id == user_id))
        )
        return [
            {
                column.name: self._json(getattr(row, column.name))
                for column in model.__table__.columns
                if column.name not in {"password_hash", "token_hash"}
            }
            for row in rows
        ]

    @classmethod
    def _json(cls, value):
        if isinstance(value, (datetime, date, UUID)):
            return str(value)
        if hasattr(value, "as_tuple"):
            return str(value)
        if isinstance(value, dict):
            return {key: cls._json(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json(item) for item in value]
        return value
