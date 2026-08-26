from fastapi import APIRouter

from nxtrep_backend.api.routes import (
    agent,
    auth,
    body,
    calendar,
    confirmations,
    exercise,
    health,
    nutrition,
    profile,
    training,
    workout,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"],
)
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(confirmations.router, prefix="/confirmations", tags=["confirmations"])
api_router.include_router(training.router, prefix="/training", tags=["training"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(workout.router, prefix="/workouts", tags=["workouts"])
api_router.include_router(nutrition.foods_router, prefix="/foods", tags=["foods"])
api_router.include_router(nutrition.nutrition_router, prefix="/nutrition", tags=["nutrition"])
api_router.include_router(body.body_router, prefix="/body", tags=["body"])
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
