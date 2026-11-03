import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from nxtrep_backend.db.models import AgentConversation, AgentRun, Confirmation, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.schemas.agent import AgentChatRequest
from nxtrep_backend.services.agent_run import AgentRunCancelledError, AgentRunService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import ConversationService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def proposal(user_id):
    return Confirmation(
        id=uuid4(),
        user_id=user_id,
        operation_type="food_create",
        after={"food": {"name": "验收草稿"}},
        reason="验收",
        impact="确认后生效",
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["checkpoint", "succeed", "fail", "abort"])
async def test_fenced_old_worker_rolls_back_late_tool_write_and_refreshes_run(method):
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            session.add(
                User(id=user_id, username=f"fenced-{user_id.hex}", password_setup_required=False)
            )
            conversation = AgentConversation(id=uuid4(), user_id=user_id)
            session.add(conversation)
            await session.flush()
            run = AgentRun(
                id=uuid4(),
                user_id=user_id,
                conversation_id=conversation.id,
                status="failed",
                request_payload={},
                started_at=datetime.now(UTC) - timedelta(minutes=15),
                error_code="AGENT_RUN_INTERRUPTED",
                checkpoint={"node": "interrupted"},
                version=2,
            )
            session.add(run)
            await session.commit()
            run_id = run.id
            late = proposal(user_id)
            late_id = late.id
            session.add(late)
            await session.flush()
            service = AgentRunService(SqlAlchemyAgentRunRepository(session))
            journal = {"confirmation_refs": [str(late_id)]}
            if method in {"checkpoint", "succeed"}:
                with pytest.raises(AgentRunCancelledError):
                    if method == "checkpoint":
                        await service.checkpoint(run=run, node="execute_branches", journal=journal)
                    else:
                        await service.succeed(
                            run=run, result_payload={"status": "completed"}, journal=journal
                        )
            elif method == "fail":
                await service.fail(
                    run=run, error_code="OTHER", error_message="迟到失败", journal=journal
                )
            else:
                await service.abort(run=run, reason="late disconnect", journal=journal)
            # Rollback expires ORM fields: safe subsequent tracing must use a
            # refreshed object, not trigger implicit asynchronous I/O.
            assert run.id == run_id and run.status == "failed"
            assert run.error_code == "AGENT_RUN_INTERRUPTED" and run.version == 2
            await session.commit()
            assert await session.get(Confirmation, late_id) is None
            assert "confirmation_refs" not in run.checkpoint
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_timeout_filters_rolled_back_proposal_refs_before_saving_failed_journal():
    user_id = uuid4()
    async with SessionFactory() as session:
        try:
            session.add(
                User(
                    id=user_id,
                    username=f"journal-timeout-{user_id.hex}",
                    password_setup_required=False,
                )
            )
            await session.flush()
            original = proposal(user_id)
            session.add(original)
            await session.commit()
            original_id = original.id
            journal = {"confirmation_refs": [str(original_id)]}

            async def failed_after_tool(*_args, **_kwargs):
                pending = proposal(user_id)
                session.add(pending)
                await session.flush()
                journal["confirmation_refs"].append(str(pending.id))
                raise TimeoutError("provider unavailable")

            graph = MagicMock()
            graph.ainvoke = AsyncMock(side_effect=failed_after_tool)
            service = AgentWorkflowService(
                graph,
                ConversationService(SqlAlchemyConversationRepository(session)),
                AgentRunService(SqlAlchemyAgentRunRepository(session)),
                tool_journal_provider=lambda: journal,
            )
            with pytest.raises(TimeoutError):
                await service.chat(user_id=user_id, request=AgentChatRequest(message="记这餐"))
            run = await session.scalar(select(AgentRun).where(AgentRun.user_id == user_id))
            assert run.status == "failed" and run.error_code == "AGENT_TIMEOUT"
            assert run.checkpoint["confirmation_refs"] == [str(original_id)]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Confirmation)
                    .where(
                        Confirmation.user_id == user_id,
                    )
                )
                == 1
            )
        finally:
            await session.rollback()
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


@pytest.mark.asyncio
async def test_run_transition_lock_serializes_stale_takeover_and_fences_late_success():
    user_id, conversation_id, run_id = uuid4(), uuid4(), uuid4()
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedRepository(SqlAlchemyAgentRunRepository):
        async def existing_confirmation_refs(self, user, refs):
            entered.set()
            await release.wait()
            return await super().existing_confirmation_refs(user, refs)

    async with SessionFactory() as owner, SessionFactory() as contender:
        transition = takeover = None
        try:
            owner.add(
                User(
                    id=user_id,
                    username=f"transition-race-{user_id.hex}",
                    password_setup_required=False,
                )
            )
            owner.add(AgentConversation(id=conversation_id, user_id=user_id))
            await owner.flush()
            old = AgentRun(
                id=run_id,
                user_id=user_id,
                conversation_id=conversation_id,
                status="running",
                request_payload={},
                started_at=datetime.now(UTC) - timedelta(minutes=15),
                checkpoint={"node": "started"},
                version=1,
            )
            owner.add(old)
            await owner.commit()
            generated = proposal(user_id)
            generated_id = generated.id
            owner.add(generated)
            await owner.flush()
            first_service = AgentRunService(PausedRepository(owner))
            transition = asyncio.create_task(
                first_service.checkpoint(
                    run=old,
                    node="execute_branches",
                        journal={"confirmation_refs": [str(generated_id)]},
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            takeover = asyncio.create_task(
                AgentRunService(
                    SqlAlchemyAgentRunRepository(contender),
                ).start(user_id=user_id, conversation_id=conversation_id, request_payload={})
            )
            await asyncio.sleep(0.05)
            # The run lock protects the entire check/journal/commit interval;
            # the contender must not close this run while its transition is open.
            assert not takeover.done()
            release.set()
            await asyncio.wait_for(transition, 3)
            replacement = await asyncio.wait_for(takeover, 3)
            assert replacement.id != run_id

            late = proposal(user_id)
            late_id = late.id
            owner.add(late)
            await owner.flush()
            with pytest.raises(AgentRunCancelledError):
                await first_service.succeed(run=old, result_payload={"status": "completed"})
            assert old.id == run_id and old.status == "failed"
            assert old.error_code == "AGENT_RUN_INTERRUPTED"
            assert await owner.get(Confirmation, late_id) is None
            assert old.checkpoint["confirmation_refs"] == [str(generated_id)]
        finally:
            release.set()
            for task in (transition, takeover):
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            await owner.rollback()
            await contender.rollback()
            await owner.execute(delete(User).where(User.id == user_id))
            await owner.commit()
