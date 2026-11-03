import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from nxtrep_backend.db.models import AgentRun, Confirmation, NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.agent import AgentChatRequest
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionPortionChange,
)
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import ConversationService
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_timeout_rolls_back_unfinished_revision_and_preserves_existing_pending_card():
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            session.add(User(id=user_id, username=f"timeout-{user_id.hex}",
                             password_setup_required=False))
            await session.flush()
            nutrition = NutritionService(SqlAlchemyNutritionRepository(session),
                                         SqlAlchemyConfirmationRepository(session))
            old = await nutrition.propose_entry(user_id=user_id, body=NutritionEntryCreateRequest(
                meal_type="lunch", eaten_at=datetime.now(UTC), items=[NutritionItemInput(
                    name="熟米饭", amount_g=200, basis_amount_g=100,
                    kcal=130, protein_g=3, carbs_g=28, fat_g=1,
                    source="model_estimated", confidence="low",
                )],
            ))
            old_id = old.id
            await session.commit()
            written = False

            async def stalled(*_args, **_kwargs):
                nonlocal written
                await nutrition.revise_pending_entry(user_id, old_id,
                    NutritionPendingEntryRevisionRequest(expected_version=1,
                        changes=[NutritionPortionChange(item_index=0, amount_g=100)]))
                written = True
                await asyncio.Event().wait()

            graph = MagicMock()
            graph.ainvoke = AsyncMock(side_effect=stalled)
            service = AgentWorkflowService(
                graph, ConversationService(SqlAlchemyConversationRepository(session)),
                AgentRunService(SqlAlchemyAgentRunRepository(session)), timeout_seconds=0.5,
            )
            with pytest.raises(TimeoutError):
                await service.chat(user_id=user_id, request=AgentChatRequest(message="米饭改100克"))
            assert written
            old = await session.get(Confirmation, old_id, populate_existing=True)
            assert old.status == "pending" and old.version == 1
            assert old.after["entry"]["items"][0]["amount_g"] == "200"
            assert await session.scalar(select(func.count()).select_from(Confirmation).where(
                Confirmation.user_id == user_id)) == 1
            assert await session.scalar(select(func.count()).select_from(NutritionEntry).where(
                NutritionEntry.user_id == user_id)) == 0
            run = await session.scalar(select(AgentRun).where(AgentRun.user_id == user_id))
            assert run.status == "failed" and run.error_code == "AGENT_TIMEOUT"
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
