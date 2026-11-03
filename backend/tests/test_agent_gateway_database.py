"""Actual proposal writes through the gateway; no provider or device calls."""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from nxtrep_backend.agents.synthesis import AgentResponseSynthesisError
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.agents.tools.registry import build_tools
from nxtrep_backend.db.models import AgentRun, Confirmation, NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentConfirmationCard,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.conversation import ConversationService
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed_context(session, user_id):
    session.add(
        User(
            id=user_id,
            username=f"gateway-database-{user_id.hex}",
            password_setup_required=False,
        )
    )
    await session.commit()
    confirmations = SqlAlchemyConfirmationRepository(session)
    return AgentToolContext(
        user_id=user_id,
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=MagicMock(),
        workout_service=MagicMock(),
        nutrition_service=NutritionService(SqlAlchemyNutritionRepository(session), confirmations),
        body_service=MagicMock(),
        confirmation_service=DatabaseConfirmationService(confirmations),
        memory_service=MagicMock(),
    )


def meal_arguments():
    return {
        "meal_type": "lunch",
        "eaten_at": datetime.now(UTC).isoformat(),
        "items": [
            {
                "name": "验收熟米饭",
                "amount_g": "200",
                "basis_amount_g": "200",
                "nutrient_basis": "total_consumed",
                "kcal": "260",
                "protein_g": "6",
                "carbs_g": "56",
                "fat_g": "2",
                "source": "model_estimated",
                "confidence": "low",
            }
        ],
        "notes": "仅用于gateway数据库验收，份量与营养均为估算。",
    }


def proposal_tool(context):
    return next(
        tool
        for tool in build_tools(context, groups={"nutrition_draft"})
        if tool.name == "propose_nutrition_entry"
    )


async def repeated_proposal(context, arguments):
    first = await proposal_tool(context).ainvoke(arguments)
    rebuilt_context = replace(context)
    assert rebuilt_context.journal is context.journal
    repeated = await proposal_tool(rebuilt_context).ainvoke(arguments)
    assert repeated == first
    return first


async def count_owned(session, model, user_id):
    return await session.scalar(
        select(func.count()).select_from(model).where(model.user_id == user_id)
    )


async def cleanup(session, user_id):
    await session.rollback()
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


def workflow(session, context, graph, *, timeout_seconds=120):
    runs = AgentRunService(SqlAlchemyAgentRunRepository(session))
    conversations = ConversationService(
        SqlAlchemyConversationRepository(session), turn_guard=runs.ensure_available
    )
    return AgentWorkflowService(
        graph,
        conversations,
        runs,
        timeout_seconds=timeout_seconds,
        tool_journal_provider=context.journal.snapshot,
    ), conversations


async def assert_failed_run_recovers_one_pending_card(session, user_id, conversations):
    run = await session.scalar(select(AgentRun).where(AgentRun.user_id == user_id))
    assert run.status == "failed"
    assert await count_owned(session, Confirmation, user_id) == 1
    assert await count_owned(session, NutritionEntry, user_id) == 0
    restored = await conversations.restore_confirmations(
        user_id=user_id, conversation_id=run.conversation_id
    )
    assert len(restored.confirmation_cards) == 1
    card = restored.confirmation_cards[0]
    assert card.status == "pending" and card.operation_type == "nutrition_entry_create"
    assert run.checkpoint["confirmation_refs"] == [str(card.confirmation_id)]
    return run, card


@pytest.mark.asyncio
async def test_real_meal_proposal_replays_after_builder_recreation_and_approves_only_once():
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            context = await seed_context(session, user_id)
            proposal = await repeated_proposal(context, meal_arguments())
            assert proposal["status"] == "confirmation_required"
            assert await count_owned(session, Confirmation, user_id) == 1
            assert await count_owned(session, NutritionEntry, user_id) == 0
            await session.commit()
            card = proposal["confirmation"]
            approved = await context.confirmation_service.approve(
                user_id, UUID(card["confirmation_id"]), card["version"]
            )
            assert approved.status == "succeeded"
            assert await count_owned(session, NutritionEntry, user_id) == 1
            await session.commit()
            entry = await session.get(NutritionEntry, UUID(approved.result["resource_id"]))
            assert entry is not None and entry.items[0]["amount_g"] == "200"
            assert context.journal.snapshot()["tool_runs"][-1]["replayed"] is True
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_chat_response_failure_recovers_real_gateway_proposal_without_claiming_saved():
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            context = await seed_context(session, user_id)
            arguments = meal_arguments()

            async def failed_response(*_args, **_kwargs):
                await repeated_proposal(context, arguments)
                raise AgentResponseSynthesisError("Text model returned an empty response")

            graph = MagicMock()
            graph.ainvoke = AsyncMock(side_effect=failed_response)
            service, conversations = workflow(session, context, graph)
            with pytest.raises(AgentResponseSynthesisError):
                await service.chat(
                    user_id=user_id,
                    request=AgentChatRequest(message="午餐熟米饭200克，先给草稿"),
                )
            run, _ = await assert_failed_run_recovers_one_pending_card(
                session, user_id, conversations
            )
            assert run.error_code == "AGENT_RESULT_INVALID"
            assert run.result_payload is None
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_stream_timeout_after_execute_checkpoint_preserves_committed_gateway_card():
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            context = await seed_context(session, user_id)
            arguments = meal_arguments()
            stream_closed = asyncio.Event()

            async def stalled_response(*_args, **_kwargs):
                try:
                    proposal = await repeated_proposal(context, arguments)
                    card = AgentConfirmationCard.model_validate(proposal["confirmation"])
                    yield (
                        "updates",
                        {
                            "execute_branches": {
                                "execution_bundle": AgentExecutionBundle(
                                    branch_results=[
                                        AgentBranchResult(
                                            task_type="nutrition_record_draft",
                                            status="completed",
                                            result={"draft": proposal["draft"], "saved": False},
                                            confirmation_cards=[card],
                                            operation_results=[proposal],
                                            requires_confirmation=True,
                                        )
                                    ]
                                )
                            }
                        },
                    )
                    await asyncio.Event().wait()
                finally:
                    stream_closed.set()

            graph = MagicMock()
            graph.astream.side_effect = stalled_response
            service, conversations = workflow(session, context, graph, timeout_seconds=2)
            events = [
                event
                async for event in service.stream(
                    user_id=user_id,
                    request=AgentChatRequest(message="午餐熟米饭200克，先给草稿"),
                )
            ]
            assert stream_closed.is_set()
            assert events[-1].event == "failed"
            assert events[-1].error_code == "AGENT_TIMEOUT"
            assert not any(event.event == "completed" for event in events)
            assert any(
                event.event == "node_completed" and event.node == "execute_branches"
                for event in events
            )
            run, _ = await assert_failed_run_recovers_one_pending_card(
                session, user_id, conversations
            )
            assert run.error_code == "AGENT_TIMEOUT" and run.result_payload is None
            async with SessionFactory() as persisted:
                assert await count_owned(persisted, Confirmation, user_id) == 1
                assert await count_owned(persisted, NutritionEntry, user_id) == 0
        finally:
            await cleanup(session, user_id)
