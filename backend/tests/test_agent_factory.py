from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

import nxtrep_backend.agents.factory as factory_module
from nxtrep_backend.agents.tools import AgentToolContext, groups_for_task
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.services.agent_handlers.body import (
    BodyAssessmentBranchHandler,
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
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.goals import GoalsService
from nxtrep_backend.services.knowledge_retrieval import KnowledgeRetrievalService
from nxtrep_backend.services.memory import MemoryService
from nxtrep_backend.services.profile import ProfileService
from nxtrep_backend.services.workout import WorkoutService


def make_model() -> MagicMock:
    model = MagicMock(spec=BaseChatModel)
    model.with_structured_output.return_value = MagicMock()
    return model


@pytest.mark.parametrize("rag_enabled", [False, True])
def test_factory_registers_handlers_and_builds_workflow(
    monkeypatch,
    rag_enabled: bool,
) -> None:
    settings = MagicMock()
    settings.rag_enabled = rag_enabled
    settings.rag_candidate_k = 20
    settings.rag_top_k = 5
    storage = MagicMock()
    text_model = make_model()
    intent_router_model = make_model()
    fallback_intent_router_model = make_model()
    vision_model = make_model()
    fallback_vision_model = make_model()
    react_agent = MagicMock(spec=CompiledStateGraph)
    compiled_graph = MagicMock(spec=CompiledStateGraph)
    graph_builder = MagicMock(return_value=compiled_graph)
    knowledge_retrieval_service = MagicMock(spec=KnowledgeRetrievalService)
    knowledge_retrieval_builder = MagicMock(
        return_value=knowledge_retrieval_service,
    )

    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        factory_module,
        "build_image_storage_provider",
        MagicMock(return_value=storage),
    )
    text_model_builder = MagicMock(return_value=text_model)
    vision_model_builder = MagicMock(return_value=vision_model)
    fallback_vision_model_builder = MagicMock(return_value=fallback_vision_model)
    react_agent_builder = MagicMock(return_value=react_agent)
    monkeypatch.setattr(
        factory_module,
        "build_text_model",
        text_model_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_fallback_text_model",
        MagicMock(return_value=None),
    )
    intent_router_model_builder = MagicMock(return_value=intent_router_model)
    fallback_intent_router_model_builder = MagicMock(
        return_value=fallback_intent_router_model,
    )
    monkeypatch.setattr(
        factory_module,
        "build_intent_router_model",
        intent_router_model_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_fallback_intent_router_model",
        fallback_intent_router_model_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_vision_model",
        vision_model_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_fallback_vision_model",
        fallback_vision_model_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_agent",
        react_agent_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_agent_execution_graph",
        graph_builder,
    )
    monkeypatch.setattr(
        factory_module,
        "build_knowledge_retrieval_service",
        knowledge_retrieval_builder,
        raising=False,
    )

    session = MagicMock(spec=AsyncSession)
    user_id = uuid4()

    service = factory_module.build_agent_workflow_service(
        session=session,
        user_id=user_id,
    )

    assert isinstance(service, AgentWorkflowService)
    assert service._graph is compiled_graph
    text_model_builder.assert_called_once_with(settings)
    vision_model_builder.assert_called_once_with(settings)
    fallback_vision_model_builder.assert_called_once_with(settings)
    react_agent_builder.assert_not_called()
    graph_builder.assert_called_once()

    nodes = graph_builder.call_args.args[0]
    assert nodes._planner._resolver._storage is storage
    assert nodes._synthesizer._model is text_model
    intent_router_model_builder.assert_called_once_with(settings)
    fallback_intent_router_model_builder.assert_called_once_with(settings)
    assert nodes._planner._intent_router._structured_models == [
        intent_router_model.with_structured_output.return_value,
        fallback_intent_router_model.with_structured_output.return_value,
    ]

    handlers = nodes._executor._handlers
    assert set(handlers) == {
        "general_question",
        "body_progress_comparison",
        "body_measurement_draft",
        "memory_write",
        "body_assessment",
        "nutrition_analysis",
        "nutrition_record_draft",
        "training_plan_draft",
        "structured_data_query",
        "knowledge_retrieval",
    }
    assert isinstance(
        handlers["general_question"],
        GeneralQuestionBranchHandler,
    )
    if rag_enabled:
        assert isinstance(
            handlers["knowledge_retrieval"],
            KnowledgeRetrievalBranchHandler,
        )
        assert handlers["knowledge_retrieval"]._service is knowledge_retrieval_service
    else:
        assert handlers["knowledge_retrieval"] is handlers["general_question"]
        assert handlers["knowledge_retrieval"]._knowledge_retrieval_enabled is False
    assert isinstance(
        handlers["body_assessment"],
        BodyAssessmentBranchHandler,
    )
    assert isinstance(
        handlers["nutrition_analysis"],
        NutritionAnalysisBranchHandler,
    )
    task = AgentIntentTask(
        task_type="general_question",
        confidence="high",
        routing_reason="general question",
    )
    built_agent = handlers["general_question"]._agent_builder(task)
    assert built_agent is react_agent
    react_agent_builder.assert_called_once()
    react_call = react_agent_builder.call_args
    assert react_call.args == (settings,)
    context = react_call.kwargs["tool_context"]
    assert isinstance(context, AgentToolContext)
    assert context.user_id == user_id
    assert isinstance(context.profile_service, ProfileService)
    assert isinstance(context.goals_service, GoalsService)
    assert isinstance(context.workout_service, WorkoutService)
    assert isinstance(context.exercises_service, ExercisesService)
    assert isinstance(context.memory_service, MemoryService)
    assert context.rag_candidate_k == 20
    assert context.rag_top_k == 5
    if rag_enabled:
        assert context.knowledge_retrieval_service is knowledge_retrieval_service
        knowledge_retrieval_builder.assert_called_once_with(
            session=session,
            settings=settings,
        )
    else:
        assert context.knowledge_retrieval_service is None
        knowledge_retrieval_builder.assert_not_called()
    assert react_call.kwargs["tool_groups"] == groups_for_task(task)
    assert react_call.kwargs["model"] is text_model
