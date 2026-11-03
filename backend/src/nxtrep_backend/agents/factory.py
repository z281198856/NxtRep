import asyncio
from dataclasses import replace
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.agents.body_vision import GlmBodyImageAssessor
from nxtrep_backend.agents.graph import build_agent_execution_graph
from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.agents.nodes import AgentGraphNodes
from nxtrep_backend.agents.nutrition_vision import (
    GlmFoodImageRecognizer,
    GlmFoodNutritionFallbackEstimator,
)
from nxtrep_backend.agents.runtime import build_agent
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.agents.tools import AgentToolContext, groups_for_task
from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.providers.models import (
    build_fallback_intent_router_model,
    build_fallback_text_model,
    build_fallback_vision_model,
    build_food_fallback_vision_model,
    build_food_vision_model,
    build_intent_router_model,
    build_text_model,
    build_vision_model,
)
from nxtrep_backend.providers.storage import (
    build_image_storage_provider,
)
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.body_progress import SqlAlchemyBodyProgressPhotoRepository
from nxtrep_backend.repositories.confirmation import (
    SqlAlchemyConfirmationRepository,
)
from nxtrep_backend.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from nxtrep_backend.repositories.exercise import (
    SqlAlchemyExercisesRepository,
)
from nxtrep_backend.repositories.goals import (
    SqlAlchemyGoalsRepository,
)
from nxtrep_backend.repositories.idempotency import SqlAlchemyIdempotencyRepository
from nxtrep_backend.repositories.media import (
    SqlAlchemyImageAssetRepository,
)
from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
from nxtrep_backend.repositories.nutrition import (
    SqlAlchemyNutritionRepository,
)
from nxtrep_backend.repositories.profile import (
    SqlAlchemyProfileRepository,
)
from nxtrep_backend.repositories.training import (
    SqlAlchemyTrainingRepository,
)
from nxtrep_backend.repositories.workout import (
    SqlAlchemyWorkoutRepository,
)
from nxtrep_backend.services.agent_context import AgentContextAssembler
from nxtrep_backend.services.agent_execution import AgentBranchExecutor
from nxtrep_backend.services.agent_handlers.body import (
    BodyAssessmentBranchHandler,
)
from nxtrep_backend.services.agent_handlers.body_progress import (
    BodyProgressComparisonBranchHandler,
)
from nxtrep_backend.services.agent_handlers.general import (
    GeneralQuestionBranchHandler,
)
from nxtrep_backend.services.agent_handlers.knowledge import (
    KnowledgeRetrievalBranchHandler,
)
from nxtrep_backend.services.agent_handlers.nutrition import (
    NutritionAnalysisBranchHandler,
)
from nxtrep_backend.services.agent_handlers.nutrition_record import (
    NutritionRecordDraftBranchHandler,
)
from nxtrep_backend.services.agent_handlers.today_training import (
    TodayTrainingQueryBranchHandler,
)
from nxtrep_backend.services.agent_handlers.training_plan import (
    TrainingPlanBranchHandler,
)
from nxtrep_backend.services.agent_media import AgentImageAssetResolver
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.agent_turn import AgentTurnService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.body_image import BodyImageWorkflow
from nxtrep_backend.services.body_progress import BodyProgressPhotoService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.conversation import (
    ConversationService,
    ModelConversationSummarizer,
)
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.goals import GoalsService
from nxtrep_backend.services.knowledge_retrieval import (
    build_knowledge_retrieval_service,
)
from nxtrep_backend.services.memory import MemoryService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.nutrition_image import (
    FoodCatalogMatcher,
    NutritionDraftCalculator,
    NutritionImageAnalysisService,
)
from nxtrep_backend.services.profile import ProfileService
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.web_search import WebSearchService
from nxtrep_backend.services.workout import WorkoutService
from nxtrep_backend.services.workout_record import WorkoutRecordService


def build_agent_workflow_service(
    *,
    session: AsyncSession,
    user_id: UUID,
) -> AgentWorkflowService:
    settings = get_settings()

    knowledge_retrieval_service = None
    if settings.rag_enabled:
        knowledge_retrieval_service = build_knowledge_retrieval_service(
            session=session,
            settings=settings,
        )

    storage = build_image_storage_provider(settings)
    image_repository = SqlAlchemyImageAssetRepository(session)

    resolver = AgentImageAssetResolver(
        image_repository,
        storage,
    )

    text_model = build_text_model(settings)
    fallback_text_model = build_fallback_text_model(settings)
    intent_router_model = build_intent_router_model(settings)
    fallback_intent_router_model = build_fallback_intent_router_model(settings)
    vision_model = build_vision_model(settings)
    fallback_vision_model = build_fallback_vision_model(settings)

    body_workflow = BodyImageWorkflow(
        resolver=resolver,
        assessor=GlmBodyImageAssessor(vision_model, fallback_vision_model),
    )
    body_handler = BodyAssessmentBranchHandler(body_workflow)
    body_progress_service = BodyProgressPhotoService(
        SqlAlchemyBodyProgressPhotoRepository(session),
        image_repository,
    )

    confirmation_repository = SqlAlchemyConfirmationRepository(session)
    training_repository = SqlAlchemyTrainingRepository(session)
    workout_repository = SqlAlchemyWorkoutRepository(session)
    nutrition_repository = SqlAlchemyNutritionRepository(session)
    memory_service = MemoryService(
        SqlAlchemyMemoryRepository(session),
    )
    run_service = AgentRunService(
        SqlAlchemyAgentRunRepository(session),
        stale_after_seconds=max(600, settings.agent_workflow_timeout_seconds + 300),
    )
    conversation_service = ConversationService(
        SqlAlchemyConversationRepository(session),
        ModelConversationSummarizer(text_model, fallback_text_model),
        turn_guard=run_service.ensure_available,
    )

    planner = AgentRequestPlanner(
        resolver=resolver,
        intent_router=AgentIntentRouter(
            intent_router_model,
            fallback_intent_router_model,
        ),
        context_assembler=AgentContextAssembler(memory_service),
        state_writer=conversation_service.save_task_state,
    )

    food_vision_model = build_food_vision_model(settings)
    food_fallback_model = build_food_fallback_vision_model(settings)
    nutrition_analysis_service = NutritionImageAnalysisService(
        recognizer=GlmFoodImageRecognizer(
            food_vision_model,
            food_fallback_model,
        ),
        fallback_estimator=GlmFoodNutritionFallbackEstimator(
            build_text_model(settings, timeout_seconds=20, max_retries=0),
        ),
        matcher=FoodCatalogMatcher(nutrition_repository),
        calculator=NutritionDraftCalculator(),
    )

    nutrition_handler = NutritionAnalysisBranchHandler(nutrition_analysis_service)
    nutrition_service = NutritionService(
        nutrition_repository,
        confirmation_repository,
    )
    training_service = TrainingService(
        training_repository,
        confirmation_repository,
    )
    workout_service = WorkoutService(
        workout_repository,
        training_repository,
        confirmation_repository,
    )

    from nxtrep_backend.repositories.water import SqlAlchemyWaterRepository
    from nxtrep_backend.services.water import WaterService

    tool_context = AgentToolContext(
        water_service=WaterService(SqlAlchemyWaterRepository(session), confirmation_repository),
        user_id=user_id,
        profile_service=ProfileService(
            SqlAlchemyProfileRepository(session),
            SqlAlchemyBodyRepository(session),
            confirmation_repository,
        ),
        goals_service=GoalsService(SqlAlchemyGoalsRepository(session)),
        exercises_service=ExercisesService(SqlAlchemyExercisesRepository(session)),
        training_service=training_service,
        workout_service=workout_service,
        workout_record_service=WorkoutRecordService(
            workout_service,
            confirmation_repository,
            ExercisesService(SqlAlchemyExercisesRepository(session)),
        ),
        nutrition_service=nutrition_service,
        body_service=BodyService(
            SqlAlchemyBodyRepository(session),
            confirmation_repository,
        ),
        confirmation_service=DatabaseConfirmationService(
            confirmation_repository,
        ),
        memory_service=memory_service,
        memory_scope_model=text_model,
        knowledge_retrieval_service=knowledge_retrieval_service,
        web_search_service=WebSearchService(settings),
        rag_candidate_k=settings.rag_candidate_k,
        rag_top_k=settings.rag_top_k,
    )

    def agent_builder(task):
        return build_agent(
            settings,
            tool_context=replace(
                tool_context,
                memory_scope=tuple(task.memory_instructions),
                task_id=task.task_id,
                task_scope={
                    **task.task_update.entities,
                    "_task_parameters": task.task_update.parameters,
                    "_reference_entities": task.task_update.reference_entities,
                }
                if task.task_update
                else {},
            ),
            tool_groups=groups_for_task(task),
            model=text_model,
            task_type=task.task_type,
            food_catalog_actions=task.food_catalog_actions,
        )

    fallback_agent_builder = None
    if fallback_text_model is not None:

        def fallback_agent_builder(task):
            return build_agent(
                settings,
                tool_context=replace(
                    tool_context,
                    memory_scope=tuple(task.memory_instructions),
                    task_id=task.task_id,
                    task_scope={
                        **task.task_update.entities,
                        "_task_parameters": task.task_update.parameters,
                        "_reference_entities": task.task_update.reference_entities,
                    }
                    if task.task_update
                    else {},
                ),
                tool_groups=groups_for_task(task),
                model=fallback_text_model,
                task_type=task.task_type,
                food_catalog_actions=task.food_catalog_actions,
            )

    general_handler = GeneralQuestionBranchHandler(
        agent_builder,
        fallback_agent_builder,
        knowledge_retrieval_enabled=(knowledge_retrieval_service is not None),
        vision_analyzer=GlmVisionAnalyzer(vision_model, fallback_vision_model),
        tool_context=tool_context,
        knowledge_preflight=lambda request: knowledge_handler.execute(request),
    )
    nutrition_record_handler = NutritionRecordDraftBranchHandler(
        nutrition_analysis_service,
        nutrition_service,
        text_handler=general_handler,
    )
    knowledge_handler = KnowledgeRetrievalBranchHandler(
        knowledge_retrieval_service,
        candidate_k=settings.rag_candidate_k,
        top_k=settings.rag_top_k,
        tool_context=tool_context,
        web_handler=general_handler,
        coverage_model=text_model,
    )
    training_plan_handler = TrainingPlanBranchHandler(general_handler, tool_context)
    structured_data_handler = TodayTrainingQueryBranchHandler(
        training_service,
        workout_service,
        general_handler,
    )
    body_progress_handler = BodyProgressComparisonBranchHandler(
        body_workflow,
        body_progress_service,
        resolver,
    )

    executor = AgentBranchExecutor(
        {
            "general_question": general_handler,
            "body_progress_comparison": body_progress_handler,
            "body_measurement_draft": general_handler,
            "water_record_draft": general_handler,
            "profile_update_draft": general_handler,
            "workout_set_update_draft": general_handler,
            "workout_set_void_draft": general_handler,
            "workout_record_draft": general_handler,
            "workout_record_update_draft": general_handler,
            "workout_record_void_draft": general_handler,
            "nutrition_entry_update_draft": general_handler,
            "nutrition_entry_delete_draft": general_handler,
            "memory_write": general_handler,
            "food_catalog_draft": general_handler,
            "confirmation_cancel": general_handler,
            "body_assessment": body_handler,
            "nutrition_analysis": nutrition_handler,
            "nutrition_record_draft": nutrition_record_handler,
            "nutrition_target_draft": general_handler,
            "training_plan_draft": training_plan_handler,
            "schedule_change_draft": general_handler,
            "training_progression_draft": general_handler,
            "structured_data_query": structured_data_handler,
            "knowledge_retrieval": knowledge_handler,
        },
        execution_lock=asyncio.Lock(),
    )

    nodes = AgentGraphNodes(
        planner=planner,
        executor=executor,
        synthesizer=AgentResponseSynthesizer(text_model, fallback_text_model),
    )

    graph = build_agent_execution_graph(nodes)

    return AgentWorkflowService(
        graph,
        conversation_service,
        run_service,
        timeout_seconds=settings.agent_workflow_timeout_seconds,
        tool_journal_provider=tool_context.journal.snapshot,
        turn_service=AgentTurnService(
            SqlAlchemyIdempotencyRepository(session),
            SqlAlchemyAgentRunRepository(session),
            stale_after_seconds=max(600, settings.agent_workflow_timeout_seconds + 300),
            workflow_timeout_seconds=settings.agent_workflow_timeout_seconds,
        ),
        trace_context=tool_context.trace_context,
    )
