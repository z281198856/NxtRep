from uuid import UUID

from fastapi import APIRouter

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.schemas.platform import NotificationResponse
from nxtrep_backend.schemas.proactive import ProactiveFeedbackRequest, ProactiveSnoozeRequest
from nxtrep_backend.services.proactive_coach import (
    ProactiveCoachService,
    ProactiveNoticeNotFoundError,
)

router = APIRouter()


@router.post("/review", response_model=list[NotificationResponse])
async def review_proactive_coaching(user: CurrentUser, session: DbSession):
    """Refresh opt-in coaching observations without changing plans or nutrition facts."""
    notifications = await ProactiveCoachService(session).review_user(user.id)
    return [
        NotificationResponse.model_validate(item, from_attributes=True) for item in notifications
    ]


@router.put("/notices/{notification_id}/feedback", response_model=NotificationResponse)
async def record_proactive_feedback(
    notification_id: UUID,
    body: ProactiveFeedbackRequest,
    user: CurrentUser,
    session: DbSession,
):
    try:
        notice = await ProactiveCoachService(session).record_feedback(
            user.id, notification_id, body.rating
        )
    except ProactiveNoticeNotFoundError as exc:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message=str(exc)) from exc
    return NotificationResponse.model_validate(notice, from_attributes=True)


@router.post("/notices/{notification_id}/snooze", response_model=NotificationResponse)
async def snooze_proactive_notice(
    notification_id: UUID, body: ProactiveSnoozeRequest, user: CurrentUser, session: DbSession
):
    try:
        notice = await ProactiveCoachService(session).snooze(user.id, notification_id, body.until)
    except ProactiveNoticeNotFoundError as exc:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=422, code="INVALID_SNOOZE_TIME", message=str(exc)) from exc
    return NotificationResponse.model_validate(notice, from_attributes=True)
