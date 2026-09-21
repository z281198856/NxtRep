from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotificationSettingsUpdate(StrictModel):
    enabled: bool | None = None
    categories: dict[str, bool] | None = None
    frequency: Literal["important_only", "daily", "realtime"] | None = None
    quiet_hours: dict | None = None
    expected_version: int = Field(ge=1)


class NotificationSettingsResponse(BaseModel):
    enabled: bool
    categories: dict
    frequency: str
    quiet_hours: dict | None
    version: int


class NotificationResponse(BaseModel):
    id: UUID
    category: str
    title: str
    body: str
    data: dict
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    list: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class PushTokenCreateRequest(StrictModel):
    device_id: str = Field(min_length=1, max_length=160)
    platform: Literal["ios", "android"]
    token: str = Field(min_length=16, max_length=4096)


class PushDeviceResponse(BaseModel):
    id: UUID
    device_id: str
    platform: str
    token_last_four: str
    created_at: datetime


class SyncMutation(StrictModel):
    resource_type: str = Field(pattern=r"^[a-z][a-z0-9_-]+$", max_length=60)
    resource_key: str = Field(min_length=1, max_length=160)
    operation: Literal["upsert", "delete"]
    base_version: int = Field(ge=0)
    payload: dict = Field(default_factory=dict)


class SyncPushRequest(StrictModel):
    device_id: str = Field(min_length=1, max_length=160)
    changes: list[SyncMutation] = Field(max_length=100)


class SyncPushResult(BaseModel):
    resource_type: str
    resource_key: str
    status: Literal["applied", "conflict"]
    version: int
    conflict_id: UUID | None = None


class SyncPushResponse(BaseModel):
    results: list[SyncPushResult]
    cursor: int


class SyncChangeResponse(BaseModel):
    cursor: int
    resource_type: str
    resource_key: str
    operation: str
    version: int
    payload: dict | None


class SyncPullResponse(BaseModel):
    changes: list[SyncChangeResponse]
    next_cursor: int
    has_more: bool


class SyncStatusResponse(BaseModel):
    latest_cursor: int
    open_conflicts: int


class SyncConflictResponse(BaseModel):
    id: UUID
    resource_type: str
    resource_key: str
    client_payload: dict
    server_payload: dict
    client_version: int
    server_version: int
    status: str
    resolution: str | None


class SyncConflictResolveRequest(StrictModel):
    resolution: Literal["client", "server", "manual"]
    merged_payload: dict | None = None


class ExportCreateRequest(StrictModel):
    include: list[str] = Field(
        default_factory=lambda: ["profile", "training", "nutrition", "body", "memories"],
        max_length=20,
    )


class ExportJobResponse(BaseModel):
    id: UUID
    status: str
    expires_at: datetime | None
    download_url: str | None
    error_code: str | None
    created_at: datetime


class ExportPayloadResponse(RootModel[dict[str, Any]]):
    """Downloaded export JSON while preserving its domain-specific top-level keys."""


class DeletionDraftCreateRequest(StrictModel):
    scope: Literal["account"] = "account"


class DeletionDraftResponse(BaseModel):
    id: UUID
    scope: str
    preview: dict
    status: str
    expires_at: datetime
    recovery_until: datetime
    version: int


class DeletionConfirmRequest(StrictModel):
    expected_version: int = Field(ge=1)
    confirmation_text: str = Field(pattern="^DELETE$")


class AuditEventResponse(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: str | None
    details: dict
    created_at: datetime


class AuditEventListResponse(BaseModel):
    list: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class WeeklyReportCreateRequest(StrictModel):
    week_start: date


class MonthlyReportCreateRequest(StrictModel):
    month_start: date


class PhaseReportCreateRequest(StrictModel):
    period_start: date
    period_end: date


class ReportResponse(BaseModel):
    id: UUID
    report_type: str
    period_start: date
    period_end: date
    facts: dict
    missing_data: list[str]
    recommendations: list[str]
    evidence: list[dict]
    version: int
    created_at: datetime


class ReportListResponse(BaseModel):
    list: list[ReportResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class AlertResponse(BaseModel):
    id: UUID
    alert_type: str
    severity: str
    title: str
    message: str
    evidence: list[dict]
    status: str
    dismissed_at: datetime | None
    created_at: datetime


class AlertListResponse(BaseModel):
    list: list[AlertResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
