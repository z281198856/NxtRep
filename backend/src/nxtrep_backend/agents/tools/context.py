import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel

from nxtrep_backend.agents.tools.journal import AgentToolJournal
from nxtrep_backend.schemas.agent import AgentMemoryInstruction
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
from nxtrep_backend.services.water import WaterService
from nxtrep_backend.services.web_search import WebSearchService
from nxtrep_backend.services.workout import WorkoutService
from nxtrep_backend.services.workout_record import WorkoutRecordService


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
    workout_record_service: WorkoutRecordService | None = None
    water_service: WaterService | None = None
    task_scope: dict = field(default_factory=dict)
    task_id: UUID | None = None
    task_type: str | None = None
    trace_context: dict = field(default_factory=dict)
    memory_scope: tuple[AgentMemoryInstruction, ...] | None = None
    memory_scope_model: BaseChatModel | None = None
    tool_runs: list[dict] = field(default_factory=list, repr=False, compare=False)
    journal: AgentToolJournal = field(default_factory=AgentToolJournal, repr=False, compare=False)
    operation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
        compare=False,
    )
    knowledge_retrieval_service: KnowledgeRetrievalService | None = None
    web_search_service: WebSearchService | None = None
    rag_candidate_k: int = 20
    rag_top_k: int = 5
