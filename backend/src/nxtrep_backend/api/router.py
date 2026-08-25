from fastapi import APIRouter

from nxtrep_backend.api.routes import (
    agent,
    auth,
    confirmations,
    health,
    profile,
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
api_router.include_router(
    profile.router,
    prefix="/profile",
    tags=["profile"],
)
