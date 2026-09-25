from calendar import monthrange
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.repositories.platform import SqlAlchemyPlatformRepository
from nxtrep_backend.schemas.platform import (
    AlertListResponse,
    AlertResponse,
    AuditEventListResponse,
    AuditEventResponse,
    DeletionConfirmRequest,
    DeletionDraftCreateRequest,
    DeletionDraftResponse,
    ExportCreateRequest,
    ExportJobResponse,
    ExportPayloadResponse,
    MonthlyReportCreateRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
    PhaseReportCreateRequest,
    PushDeviceResponse,
    PushTokenCreateRequest,
    ReportListResponse,
    ReportResponse,
    SyncChangeResponse,
    SyncConflictResolveRequest,
    SyncConflictResponse,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncStatusResponse,
    WeeklyReportCreateRequest,
)
from nxtrep_backend.services.platform import (
    PlatformConflictError,
    PlatformNotFoundError,
    PlatformService,
)

notification_settings_router = APIRouter()
notifications_router = APIRouter()
devices_router = APIRouter()
sync_router = APIRouter()
exports_router = APIRouter()
deletion_router = APIRouter()
audit_router = APIRouter()
reports_router = APIRouter()
alerts_router = APIRouter()


def _service(session: DbSession) -> PlatformService:
    return PlatformService(SqlAlchemyPlatformRepository(session))


def _raise_platform_error(exc: RuntimeError) -> None:
    if isinstance(exc, PlatformNotFoundError):
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, PlatformConflictError):
        raise ApiError(status_code=409, code="RESOURCE_CONFLICT", message=str(exc)) from exc
    raise exc


def _export_response(item) -> ExportJobResponse:
    return ExportJobResponse(
        id=item.id,
        status=item.status,
        expires_at=item.expires_at,
        download_url=(
            f"/api/v1/exports/{item.id}/download" if item.status == "completed" else None
        ),
        error_code=item.error_code,
        created_at=item.created_at,
    )


@notification_settings_router.get("", response_model=NotificationSettingsResponse)
async def get_notification_settings(user: CurrentUser, session: DbSession):
    return NotificationSettingsResponse.model_validate(
        await _service(session).get_notification_settings(user.id), from_attributes=True
    )


@notification_settings_router.patch("", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    body: NotificationSettingsUpdate, user: CurrentUser, session: DbSession
):
    try:
        item = await _service(session).update_notification_settings(user.id, body)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return NotificationSettingsResponse.model_validate(item, from_attributes=True)


@notifications_router.get("", response_model=NotificationListResponse)
async def list_notifications(
    user: CurrentUser,
    session: DbSession,
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(default=None, max_length=40),
):
    items, total = await SqlAlchemyPlatformRepository(session).list_notifications(
        user.id, unread_only, page, page_size, category
    )
    return NotificationListResponse(
        list=[NotificationResponse.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@notifications_router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(notification_id: UUID, user: CurrentUser, session: DbSession):
    try:
        item = await _service(session).mark_notification_read(user.id, notification_id)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return NotificationResponse.model_validate(item, from_attributes=True)


@devices_router.post("/push-tokens", response_model=PushDeviceResponse, status_code=201)
async def register_push_token(body: PushTokenCreateRequest, user: CurrentUser, session: DbSession):
    item = await _service(session).register_push_device(user.id, body)
    return PushDeviceResponse.model_validate(item, from_attributes=True)


@devices_router.delete("/push-tokens/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_push_token(device_id: UUID, user: CurrentUser, session: DbSession):
    try:
        await _service(session).revoke_push_device(user.id, device_id)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sync_router.post("/push", response_model=SyncPushResponse)
async def sync_push(
    body: SyncPushRequest, idempotency_key: IdempotencyKey, user: CurrentUser, session: DbSession
):
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /sync/push", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, SyncPushResponse, 200):
        return replayed
    results, cursor = await _service(session).sync_push(user.id, body)
    response = SyncPushResponse(results=results, cursor=cursor)
    await complete_idempotent(idem, decision, response, 200)
    return response


@sync_router.get("/pull", response_model=SyncPullResponse)
async def sync_pull(
    user: CurrentUser,
    session: DbSession,
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    rows = await SqlAlchemyPlatformRepository(session).list_changes(user.id, cursor, limit)
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].sequence if rows else cursor
    return SyncPullResponse(
        changes=[
            SyncChangeResponse(
                cursor=item.sequence,
                resource_type=item.resource_type,
                resource_key=item.resource_key,
                operation=item.operation,
                version=item.version,
                payload=item.payload,
            )
            for item in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@sync_router.get("/status", response_model=SyncStatusResponse)
async def sync_status(user: CurrentUser, session: DbSession):
    repository = SqlAlchemyPlatformRepository(session)
    return SyncStatusResponse(
        latest_cursor=await repository.latest_cursor(user.id),
        open_conflicts=await repository.count_open_conflicts(user.id),
    )


@sync_router.get("/conflicts", response_model=list[SyncConflictResponse])
async def list_sync_conflicts(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, _ = await SqlAlchemyPlatformRepository(session).list_conflicts(user.id, page, page_size)
    return [SyncConflictResponse.model_validate(item, from_attributes=True) for item in items]


@sync_router.post("/conflicts/{conflict_id}/resolve", response_model=SyncConflictResponse)
async def resolve_sync_conflict(
    conflict_id: UUID, body: SyncConflictResolveRequest, user: CurrentUser, session: DbSession
):
    try:
        item = await _service(session).resolve_conflict(user.id, conflict_id, body)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return SyncConflictResponse.model_validate(item, from_attributes=True)


@exports_router.post("", response_model=ExportJobResponse, status_code=201)
async def create_export(
    body: ExportCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
):
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /exports", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ExportJobResponse, 201):
        return replayed
    response = _export_response(await _service(session).create_export(user.id, body.include))
    await complete_idempotent(idem, decision, response, 201)
    return response


@exports_router.get("", response_model=list[ExportJobResponse])
async def list_exports(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, _ = await SqlAlchemyPlatformRepository(session).list_exports(user.id, page, page_size)
    return [_export_response(item) for item in items]


@exports_router.get("/{export_id}", response_model=ExportJobResponse)
async def get_export(export_id: UUID, user: CurrentUser, session: DbSession):
    item = await SqlAlchemyPlatformRepository(session).get_export(user.id, export_id)
    if item is None:
        raise ApiError(status_code=404, code="EXPORT_NOT_FOUND", message="Export not found")
    return _export_response(item)


@exports_router.get("/{export_id}/download", response_model=ExportPayloadResponse)
async def download_export(
    export_id: UUID,
    user: CurrentUser,
    session: DbSession,
    response: Response,
) -> ExportPayloadResponse:
    item = await SqlAlchemyPlatformRepository(session).get_export(user.id, export_id)
    if item is None or item.status != "completed" or item.payload is None:
        raise ApiError(status_code=404, code="EXPORT_NOT_FOUND", message="Export not found")
    if item.expires_at and item.expires_at <= datetime.now(UTC):
        raise ApiError(status_code=410, code="EXPORT_EXPIRED", message="Export has expired")
    response.headers["Content-Disposition"] = f'attachment; filename="nxtrep-{export_id}.json"'
    return ExportPayloadResponse(root=item.payload)


@deletion_router.post("", response_model=DeletionDraftResponse, status_code=201)
async def create_deletion_draft(
    body: DeletionDraftCreateRequest, user: CurrentUser, session: DbSession
):
    item = await _service(session).create_deletion_draft(user.id)
    return DeletionDraftResponse.model_validate(item, from_attributes=True)


@deletion_router.post("/{draft_id}/confirm", response_model=DeletionDraftResponse)
async def confirm_deletion(
    draft_id: UUID, body: DeletionConfirmRequest, user: CurrentUser, session: DbSession
):
    try:
        item = await _service(session).confirm_deletion(user, draft_id, body)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return DeletionDraftResponse.model_validate(item, from_attributes=True)


@audit_router.get("", response_model=AuditEventListResponse)
async def list_audit_events(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await SqlAlchemyPlatformRepository(session).list_audit(user.id, page, page_size)
    return AuditEventListResponse(
        list=[AuditEventResponse.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@reports_router.get("", response_model=ReportListResponse)
async def list_reports(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await SqlAlchemyPlatformRepository(session).list_reports(
        user.id, page, page_size
    )
    return ReportListResponse(
        list=[ReportResponse.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@reports_router.post("/weekly", response_model=ReportResponse)
async def generate_weekly_report(
    body: WeeklyReportCreateRequest, user: CurrentUser, session: DbSession
):
    item = await _service(session).generate_weekly_report(user.id, body.week_start)
    return ReportResponse.model_validate(item, from_attributes=True)


@reports_router.post("/monthly", response_model=ReportResponse)
async def generate_monthly_report(
    body: MonthlyReportCreateRequest, user: CurrentUser, session: DbSession
):
    if body.month_start.day != 1:
        raise ApiError(
            status_code=422,
            code="INVALID_MONTH_START",
            message="month_start must be the first day",
        )
    end = date(
        body.month_start.year,
        body.month_start.month,
        monthrange(body.month_start.year, body.month_start.month)[1],
    )
    item = await _service(session).generate_report(user.id, "monthly", body.month_start, end)
    return ReportResponse.model_validate(item, from_attributes=True)


@reports_router.post("/phase", response_model=ReportResponse)
async def generate_phase_report(
    body: PhaseReportCreateRequest, user: CurrentUser, session: DbSession
):
    try:
        item = await _service(session).generate_report(
            user.id, "phase", body.period_start, body.period_end
        )
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return ReportResponse.model_validate(item, from_attributes=True)


@reports_router.get("/{report_id}", response_model=ReportResponse)
async def get_report(report_id: UUID, user: CurrentUser, session: DbSession):
    item = await SqlAlchemyPlatformRepository(session).get_report(user.id, report_id)
    if item is None:
        raise ApiError(status_code=404, code="REPORT_NOT_FOUND", message="Report not found")
    return ReportResponse.model_validate(item, from_attributes=True)


@alerts_router.get("", response_model=AlertListResponse)
async def list_alerts(
    user: CurrentUser,
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(open|dismissed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    await _service(session).refresh_alerts(user.id)
    items, total = await SqlAlchemyPlatformRepository(session).list_alerts(
        user.id, status_filter, page, page_size
    )
    return AlertListResponse(
        list=[AlertResponse.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@alerts_router.post("/{alert_id}/dismiss", response_model=AlertResponse)
@alerts_router.post("/{alert_id}:dismiss", response_model=AlertResponse, include_in_schema=False)
async def dismiss_alert(alert_id: UUID, user: CurrentUser, session: DbSession):
    try:
        item = await _service(session).dismiss_alert(user.id, alert_id)
    except RuntimeError as exc:
        _raise_platform_error(exc)
    return AlertResponse.model_validate(item, from_attributes=True)
