from fastapi import APIRouter

from nxtrep_backend.api.routes import (
    account,
    admin,
    agent,
    auth,
    body,
    body_progress,
    calendar,
    confirmations,
    exercise,
    exercise_media,
    health,
    media,
    memory,
    nutrition,
    platform,
    proactive,
    profile,
    settings,
    training,
    workout,
)
from nxtrep_backend.schemas.error import ErrorResponse

api_router = APIRouter(
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Request validation failed using the standard error envelope.",
        },
        "default": {
            "model": ErrorResponse,
            "description": "Error response using the standard error envelope.",
        },
    }
)
api_router.include_router(health.router)
api_router.include_router(account.router, tags=["account"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"],
)
api_router.include_router(memory.router, prefix="/memories", tags=["memories"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(proactive.router, prefix="/agent/proactive", tags=["agent"])
api_router.include_router(confirmations.router, prefix="/confirmations", tags=["confirmations"])
api_router.include_router(training.router, prefix="/training", tags=["training"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(workout.router, prefix="/workouts", tags=["workouts"])
api_router.include_router(nutrition.foods_router, prefix="/foods", tags=["foods"])
api_router.include_router(nutrition.nutrition_router, prefix="/nutrition", tags=["nutrition"])
api_router.include_router(nutrition.recipes_router, prefix="/recipes", tags=["recipes"])
api_router.include_router(body.body_router, prefix="/body", tags=["body"])
api_router.include_router(
    body_progress.router,
    prefix="/body/progress-photos",
    tags=["body-progress-photos"],
)
api_router.include_router(
    body_progress.router,
    prefix="/body/photos",
    tags=["body-photos"],
)
api_router.include_router(body.progress_router, prefix="/progress", tags=["progress"])
api_router.include_router(
    profile.router,
    prefix="/profile",
    tags=["profile"],
)
api_router.include_router(
    exercise.router,
    prefix="/exercises",
    tags=["exercises"],
)
api_router.include_router(
    exercise.content_router,
    prefix="/exercise-content",
    tags=["exercise-content"],
)
api_router.include_router(
    exercise_media.router,
    prefix="/exercise-media",
    tags=["exercise-media"],
)
api_router.include_router(
    media.router,
    prefix="/media",
    tags=["media"],
)
api_router.include_router(
    platform.notification_settings_router,
    prefix="/notification-settings",
    tags=["notifications"],
)
api_router.include_router(
    platform.notifications_router,
    prefix="/notifications",
    tags=["notifications"],
)
api_router.include_router(
    platform.devices_router,
    prefix="/devices",
    tags=["devices"],
)
api_router.include_router(platform.sync_router, prefix="/sync", tags=["sync"])
api_router.include_router(platform.exports_router, prefix="/exports", tags=["exports"])
api_router.include_router(
    platform.deletion_router,
    prefix="/deletion-drafts",
    tags=["deletion"],
)
api_router.include_router(
    platform.audit_router,
    prefix="/audit-events",
    tags=["audit"],
)
api_router.include_router(platform.reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(platform.alerts_router, prefix="/alerts", tags=["alerts"])
