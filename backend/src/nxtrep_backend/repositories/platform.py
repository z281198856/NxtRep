from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    AppAlert,
    AppNotification,
    AuditEvent,
    DeletionDraft,
    ExportJob,
    GeneratedReport,
    NotificationSetting,
    PushDevice,
    SyncChange,
    SyncConflict,
    SyncResource,
)


class SqlAlchemyPlatformRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_notification_settings(self, user_id: UUID, *, lock: bool = False):
        statement = select(NotificationSetting).where(NotificationSetting.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def add(self, item):
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_notifications(
        self,
        user_id: UUID,
        unread_only: bool,
        page: int,
        page_size: int,
        category: str | None = None,
    ):
        conditions = [AppNotification.user_id == user_id]
        if unread_only:
            conditions.append(AppNotification.read_at.is_(None))
        if category is not None:
            conditions.append(AppNotification.category == category)
        total = await self.session.scalar(
            select(func.count()).select_from(AppNotification).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(AppNotification)
                .where(*conditions)
                .order_by(AppNotification.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_notification(self, user_id: UUID, item_id: UUID, *, lock: bool = False):
        statement = select(AppNotification).where(
            AppNotification.id == item_id, AppNotification.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_push_device(self, user_id: UUID, device_id: str, *, lock: bool = False):
        statement = select(PushDevice).where(
            PushDevice.user_id == user_id, PushDevice.device_id == device_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_push_device_by_id(self, user_id: UUID, item_id: UUID, *, lock: bool = False):
        statement = select(PushDevice).where(
            PushDevice.id == item_id, PushDevice.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_sync_resource(
        self, user_id: UUID, resource_type: str, resource_key: str, *, lock: bool = False
    ):
        statement = select(SyncResource).where(
            SyncResource.user_id == user_id,
            SyncResource.resource_type == resource_type,
            SyncResource.resource_key == resource_key,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def latest_cursor(self, user_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.max(SyncChange.sequence)).where(SyncChange.user_id == user_id)
            )
            or 0
        )

    async def list_changes(self, user_id: UUID, after: int, limit: int):
        return list(
            await self.session.scalars(
                select(SyncChange)
                .where(SyncChange.user_id == user_id, SyncChange.sequence > after)
                .order_by(SyncChange.sequence)
                .limit(limit + 1)
            )
        )

    async def list_conflicts(self, user_id: UUID, page: int, page_size: int):
        condition = SyncConflict.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(SyncConflict).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(SyncConflict)
                .where(condition)
                .order_by(SyncConflict.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def count_open_conflicts(self, user_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(SyncConflict)
                .where(SyncConflict.user_id == user_id, SyncConflict.status == "open")
            )
            or 0
        )

    async def get_conflict(self, user_id: UUID, conflict_id: UUID, *, lock: bool = False):
        statement = select(SyncConflict).where(
            SyncConflict.id == conflict_id, SyncConflict.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_exports(self, user_id: UUID, page: int, page_size: int):
        condition = ExportJob.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(ExportJob).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(ExportJob)
                .where(condition)
                .order_by(ExportJob.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_export(self, user_id: UUID, export_id: UUID):
        return await self.session.scalar(
            select(ExportJob).where(ExportJob.id == export_id, ExportJob.user_id == user_id)
        )

    async def get_deletion_draft(self, user_id: UUID, draft_id: UUID, *, lock: bool = False):
        statement = select(DeletionDraft).where(
            DeletionDraft.id == draft_id, DeletionDraft.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_audit(self, user_id: UUID, page: int, page_size: int):
        condition = AuditEvent.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(AuditEvent).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(AuditEvent)
                .where(condition)
                .order_by(AuditEvent.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def list_reports(self, user_id: UUID, page: int, page_size: int):
        condition = GeneratedReport.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(GeneratedReport).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(GeneratedReport)
                .where(condition)
                .order_by(GeneratedReport.period_start.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_report(self, user_id: UUID, report_id: UUID):
        return await self.session.scalar(
            select(GeneratedReport).where(
                GeneratedReport.id == report_id, GeneratedReport.user_id == user_id
            )
        )

    async def get_report_period(
        self, user_id: UUID, report_type: str, start, end, *, lock: bool = False
    ):
        statement = select(GeneratedReport).where(
            GeneratedReport.user_id == user_id,
            GeneratedReport.report_type == report_type,
            GeneratedReport.period_start == start,
            GeneratedReport.period_end == end,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_alerts(self, user_id: UUID, status: str | None, page: int, page_size: int):
        conditions = [AppAlert.user_id == user_id]
        if status:
            conditions.append(AppAlert.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(AppAlert).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(AppAlert)
                .where(*conditions)
                .order_by(AppAlert.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_alert(self, user_id: UUID, alert_id: UUID, *, lock: bool = False):
        statement = select(AppAlert).where(AppAlert.id == alert_id, AppAlert.user_id == user_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_open_alert_by_type(self, user_id: UUID, alert_type: str):
        return await self.session.scalar(
            select(AppAlert).where(
                AppAlert.user_id == user_id,
                AppAlert.alert_type == alert_type,
                AppAlert.status == "open",
            )
        )
