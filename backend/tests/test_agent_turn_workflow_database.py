import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.db.models import AgentMessage, AgentRun, Confirmation, IdempotencyRecord, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.idempotency import SqlAlchemyIdempotencyRepository
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatRequest,
    AgentConfirmationCard,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_run import AgentRunService
from nxtrep_backend.services.agent_turn import AgentTurnReplayError, AgentTurnService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import AgentConversationNotFoundError, ConversationService
from nxtrep_backend.services.idempotency import IdempotencyRequestInProgressError

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


class StubGraph:
    def __init__(self, session, *, fail_after_proposal=False):
        self.session = session
        self.calls = 0
        self.fail_after_proposal = fail_after_proposal
        self.journal = {"confirmation_refs": []}
        self.message = "已读取资料，今天按原计划训练即可。"

    async def result(self, state):
        self.calls += 1
        cards = []
        if self.fail_after_proposal:
            card = Confirmation(
                user_id=state["user_id"],
                operation_type="food_create",
                after={"food": {"name": "验收鸡腿饭"}},
                reason="验收",
                impact="确认后生效",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            self.session.add(card)
            await self.session.flush()
            self.journal["confirmation_refs"].append(str(card.id))
            cards = [AgentConfirmationCard.model_validate(confirmation_payload(card))]
        return {
            "response_message": self.message,
            "conversation_context": state["conversation_context"],
            "execution_bundle": AgentExecutionBundle(
                branch_results=[
                    AgentBranchResult(
                        task_type="general_question",
                        status="completed",
                        result={"answer": self.message},
                        confirmation_cards=cards,
                        requires_confirmation=bool(cards),
                    )
                ]
            ),
        }

    async def ainvoke(self, state):
        result = await self.result(state)
        if self.fail_after_proposal:
            raise RuntimeError("模拟生成回复失败")
        return result

    async def astream(self, state, stream_mode):
        result = await self.result(state)
        yield "updates", {"execute_branches": {"execution_bundle": result["execution_bundle"]}}
        if self.fail_after_proposal:
            raise RuntimeError("模拟生成回复失败")
        yield (
            "custom",
            {"event": "message_delta", "node": "synthesize_response", "delta": self.message},
        )
        yield "updates", {"synthesize_response": result}


def workflow(session, graph, *, turns=None):
    runs = AgentRunService(SqlAlchemyAgentRunRepository(session))
    conversations = ConversationService(
        SqlAlchemyConversationRepository(session), turn_guard=runs.ensure_available
    )
    turns = turns or AgentTurnService(
        SqlAlchemyIdempotencyRepository(session), SqlAlchemyAgentRunRepository(session)
    )
    return AgentWorkflowService(
        graph,
        conversations,
        runs,
        monitor=MagicMock(),
        turn_service=turns,
        tool_journal_provider=lambda: graph.journal,
    ), turns


async def seed(session):
    user_id = uuid4()
    session.add(
        User(id=user_id, username=f"workflow-turn-{user_id.hex}", password_setup_required=False)
    )
    await session.commit()
    return user_id


async def cleanup(session, user_id):
    await session.rollback()
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["chat", "stream"])
async def test_workflow_duplicate_client_turn_replays_without_new_messages_or_graph_execution(
    transport,
):
    async with SessionFactory() as session:
        user_id = await seed(session)
        try:
            graph = StubGraph(session)
            runner, _ = workflow(session, graph)
            request = AgentChatRequest(message="今天怎么训练", client_turn_id=uuid4())
            if transport == "chat":
                response = await runner.chat(user_id=user_id, request=request)
                replay = await runner.chat(user_id=user_id, request=request)
            else:
                events = [event async for event in runner.stream(user_id=user_id, request=request)]
                assert events[-1].event == "completed"
                response = events[-1].response
                replay_events = [
                    event async for event in runner.stream(user_id=user_id, request=request)
                ]
                assert [event.event for event in replay_events] == [
                    "run_started",
                    "message_delta",
                    "completed",
                ]
                replay = replay_events[-1].response
            assert graph.calls == 1 and replay == response
            assert (
                await session.scalar(
                    select(func.count()).select_from(AgentRun).where(AgentRun.user_id == user_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMessage)
                    .where(AgentMessage.conversation_id == response.conversation_id)
                )
                == 2
            )
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_workflow_terminal_run_recovers_gap_before_idempotency_cache_completion(monkeypatch):
    async with SessionFactory() as session:
        user_id = await seed(session)
        try:
            graph = StubGraph(session)
            runner, turns = workflow(session, graph)
            request = AgentChatRequest(message="已完成但回复断线", client_turn_id=uuid4())
            original = turns.complete

            async def skip_cache_once(**kwargs):
                pass

            monkeypatch.setattr(turns, "complete", skip_cache_once)
            response = await runner.chat(user_id=user_id, request=request)
            row = await session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id)
            )
            assert row.status == "processing"
            monkeypatch.setattr(turns, "complete", original)
            replay = await runner.chat(user_id=user_id, request=request)
            assert replay == response and graph.calls == 1
            await session.refresh(row)
            assert row.status == "completed"
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_workflow_failure_after_committed_proposal_retains_refs_and_retry_never_reexecutes():
    async with SessionFactory() as session:
        user_id = await seed(session)
        try:
            graph = StubGraph(session, fail_after_proposal=True)
            runner, _ = workflow(session, graph)
            request = AgentChatRequest(message="创建验收食品草稿", client_turn_id=uuid4())
            events = [event async for event in runner.stream(user_id=user_id, request=request)]
            assert events[-1].event == "failed"
            run = await session.scalar(select(AgentRun).where(AgentRun.user_id == user_id))
            assert run.status == "failed" and len(run.checkpoint["confirmation_refs"]) == 1
            original_run_id, conversation_id = run.id, run.conversation_id
            refs = await SqlAlchemyConversationRepository(session).list_conversation_confirmations(
                user_id=user_id, conversation_id=conversation_id
            )
            assert len(refs) == 1 and refs[0].status == "pending"
            retry = [event async for event in runner.stream(user_id=user_id, request=request)]
            assert (
                len(retry) == 1
                and retry[0].event == "failed"
                and retry[0].run_id == original_run_id
            )
            assert graph.calls == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMessage)
                    .where(AgentMessage.conversation_id == conversation_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Confirmation)
                    .where(Confirmation.user_id == user_id)
                )
                == 1
            )
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_workflow_running_same_turn_returns_original_run_id_and_init_failure_is_cached():
    async with SessionFactory() as session:
        user_id = await seed(session)
        try:
            graph = StubGraph(session)
            runner, turns = workflow(session, graph)
            request = AgentChatRequest(message="等待中的请求", client_turn_id=uuid4())
            response = await runner.chat(user_id=user_id, request=request)
            run_id = response.run_id
            run = await session.get(AgentRun, run_id)
            run.status, run.result_payload = "running", None
            await session.commit()
            retry = [event async for event in runner.stream(user_id=user_id, request=request)]
            assert len(retry) == 1 and retry[0].event == "failed" and retry[0].run_id == run_id
            assert retry[0].error_code == "AGENT_TURN_IN_PROGRESS"
            invalid = AgentChatRequest(
                message="找不到对话", conversation_id=uuid4(), client_turn_id=uuid4()
            )
            with pytest.raises(AgentConversationNotFoundError):
                await runner.chat(user_id=user_id, request=invalid)
            row = await session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.idempotency_key == invalid.client_turn_id,
                )
            )
            assert row.status == "completed"
            with pytest.raises(AgentTurnReplayError):
                await turns.begin(user_id=user_id, request=invalid)
            assert graph.calls == 1
        finally:
            await cleanup(session, user_id)


@pytest.mark.asyncio
async def test_chat_retry_of_running_turn_returns_in_progress_with_original_id():
    async with SessionFactory() as session:
        user_id = await seed(session)
        try:
            graph = StubGraph(session)
            runner, _ = workflow(session, graph)
            request = AgentChatRequest(message="读取历史", client_turn_id=uuid4())
            response = await runner.chat(user_id=user_id, request=request)
            run_id = response.run_id
            run = await session.get(AgentRun, run_id)
            run.status, run.result_payload = "running", None
            await session.commit()
            with pytest.raises(IdempotencyRequestInProgressError) as caught:
                await runner.chat(user_id=user_id, request=request)
            assert caught.value.run_id == run_id and graph.calls == 1
        finally:
            await cleanup(session, user_id)
