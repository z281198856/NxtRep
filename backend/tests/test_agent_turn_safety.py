import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.routes import agent
from nxtrep_backend.db.models import AgentConversation, AgentMessage, AgentRun, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_run import AgentRunInProgressError, AgentRunService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import ConversationService


@pytest.mark.asyncio
async def test_busy_chat_has_distinct_safe_409_response(monkeypatch):
    service = SimpleNamespace(
        chat=AsyncMock(side_effect=AgentRunInProgressError("private run details")),
    )
    monkeypatch.setattr(agent, "build_agent_workflow_service", lambda **_: service)
    with pytest.raises(ApiError) as caught:
        await agent.chat(
            body=AgentChatRequest(message="继续"), user_id=uuid4(), session=MagicMock(),
        )
    assert caught.value.status_code == 409
    assert caught.value.code == "AGENT_CONVERSATION_BUSY"
    assert "上一条消息" in caught.value.message
    assert "private" not in caught.value.message


def workflow(session, graph):
    runs = AgentRunService(SqlAlchemyAgentRunRepository(session))
    conversations = ConversationService(
        SqlAlchemyConversationRepository(session), turn_guard=runs.ensure_available,
    )
    return AgentWorkflowService(graph, conversations, runs)


@pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")
@pytest.mark.asyncio
async def test_two_sessions_cannot_append_or_execute_overlapping_conversation_turns():
    user_id, conversation_id = uuid4(), uuid4()
    entered, release = asyncio.Event(), asyncio.Event()
    first_task = None
    async with SessionFactory() as setup:
        setup.add(User(id=user_id, username=f"turn-safety-{user_id.hex}",
                       password_setup_required=False))
        await setup.flush()
        setup.add(AgentConversation(id=conversation_id, user_id=user_id))
        await setup.commit()
    try:
        async with SessionFactory() as first, SessionFactory() as second:
            async def blocked_graph(*_args, **_kwargs):
                entered.set()
                await release.wait()
                return {
                    "response_message": "第一轮完成",
                    "execution_bundle": AgentExecutionBundle(branch_results=[
                        AgentBranchResult(task_type="general_question", status="completed",
                                          result={"answer": "第一轮完成"}),
                    ]),
                }

            first_graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=blocked_graph))
            second_graph = SimpleNamespace(ainvoke=AsyncMock())
            first_task = asyncio.create_task(workflow(first, first_graph).chat(
                user_id=user_id,
                request=AgentChatRequest(conversation_id=conversation_id, message="第一轮"),
            ))
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(AgentRunInProgressError):
                await workflow(second, second_graph).chat(
                    user_id=user_id,
                    request=AgentChatRequest(conversation_id=conversation_id, message="第二轮"),
                )
            second_graph.ainvoke.assert_not_awaited()
            await second.rollback()
            assert await second.scalar(select(func.count()).select_from(AgentMessage).where(
                AgentMessage.conversation_id == conversation_id,
            )) == 1
            assert await second.scalar(select(func.count()).select_from(AgentRun).where(
                AgentRun.conversation_id == conversation_id,
            )) == 1
            await second.rollback()
            release.set()
            response = await asyncio.wait_for(first_task, timeout=5)
            assert response.status == "completed"
            messages = list(await second.scalars(select(AgentMessage).where(
                AgentMessage.conversation_id == conversation_id,
            ).order_by(AgentMessage.sequence)))
            assert [(item.sequence, item.content) for item in messages] == [
                (1, "第一轮"), (2, "第一轮完成"),
            ]
    finally:
        release.set()
        if first_task is not None and not first_task.done():
            first_task.cancel()
            await asyncio.gather(first_task, return_exceptions=True)
        async with SessionFactory() as cleanup:
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


@pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")
@pytest.mark.asyncio
async def test_finish_reloads_message_sequence_from_database_after_other_writer():
    user_id, conversation_id = uuid4(), uuid4()
    async with SessionFactory() as first:
        try:
            first.add(User(id=user_id, username=f"turn-sequence-{user_id.hex}",
                           password_setup_required=False))
            await first.flush()
            stale = AgentConversation(id=conversation_id, user_id=user_id)
            first.add(stale)
            await first.commit()
            # Another legitimate DB writer advanced the sequence after this session
            # loaded its conversation. The identity map must not hide that change.
            async with SessionFactory() as other:
                repository = SqlAlchemyConversationRepository(other)
                current = await repository.get_for_user(
                    user_id=user_id, conversation_id=conversation_id, lock=True,
                )
                await repository.append_message(
                    conversation=current, role="user", content="另一条已保存消息",
                )
                await other.commit()
            assert stale.next_sequence == 1
            message = await ConversationService(
                SqlAlchemyConversationRepository(first),
            ).finish_turn(conversation=stale, assistant_message="补充回复")
            assert message.sequence == 2
            await first.commit()
        finally:
            await first.rollback()
            await first.execute(delete(User).where(User.id == user_id))
            await first.commit()
