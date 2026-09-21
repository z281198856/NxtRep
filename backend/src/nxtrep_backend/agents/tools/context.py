import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.goals import GoalsService
from nxtrep_backend.services.knowledge_retrieval import (
    KnowledgeRetrievalService,
)
from nxtrep_backend.services.memory import MemoryService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.profile import ProfileService
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutService


@dataclass(frozen=True, slots=True)
class AgentToolContext:
    """Request-scoped, authenticated dependencies captured by Agent tools."""

    user_id: UUID
    profile_service: ProfileService
    goals_service: GoalsService
    exercises_service: ExercisesService
    training_service: TrainingService
    workout_service: WorkoutService
    nutrition_service: NutritionService
    body_service: BodyService
    confirmation_service: DatabaseConfirmationService
    memory_service: MemoryService
    operation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
        compare=False,
    )
    knowledge_retrieval_service: KnowledgeRetrievalService | None = None
    rag_candidate_k: int = 20
    rag_top_k: int = 5
