from fastapi import APIRouter

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.schemas.platform import NotificationResponse
from nxtrep_backend.services.proactive_coach import ProactiveCoachService

router = APIRouter()


@router.post("/review", response_model=list[NotificationResponse])
async def review_proactive_coaching(user: CurrentUser, session: DbSession):
    """Refresh opt-in coaching observations without changing plans or nutrition facts."""
    notifications = await ProactiveCoachService(session).review_user(user.id)
    return [
        NotificationResponse.model_validate(item, from_attributes=True) for item in notifications
    ]
