import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from nxtrep_backend.db.models import AgentConversation, AgentRun, IdempotencyRecord, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.repositories.idempotency import SqlAlchemyIdempotencyRepository
from nxtrep_backend.schemas.agent import AgentChatRequest, AgentChatResponse
from nxtrep_backend.services.agent_run import AgentRunCancelledError, AgentRunService
from nxtrep_backend.services.agent_turn import AgentTurnReplayError, AgentTurnService
from nxtrep_backend.services.idempotency import (
    IdempotencyKeyConflictError,
    IdempotencyRequestInProgressError,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def service(session):
    return AgentTurnService(
        SqlAlchemyIdempotencyRepository(session), SqlAlchemyAgentRunRepository(session)
    )


async def seed(session):
    user_id, conversation_id = uuid4(), uuid4()
    session.add(
        User(id=user_id, username=f"turn-replay-{user_id.hex}", password_setup_required=False)
    )
    session.add(AgentConversation(id=conversation_id, user_id=user_id))
    await session.commit()
    return user_id, conversation_id


async def terminal_run(session, user_id, conversation_id, request, decision):
    run = AgentRun(
        id=uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        status="running",
        started_at=datetime.now(UTC),
        checkpoint={"node": "started"},
        request_payload=request.model_copy(update={"conversation_id": conversation_id}).model_dump(
            mode="json"
        ),
    )
    session.add(run)
    await session.commit()
    await service(session).attach_run(decision=decision, run=run)
    response = AgentChatResponse(
        message="已生成草稿，请确认。", conversation_id=conversation_id, run_id=run.id
    )
    run.status = "succeeded"
    run.result_payload = response.model_dump(mode="json")
    run.finished_at = datetime.now(UTC)
    await session.commit()
    return run, response


async def cleanup(session, user_ids):
    await session.rollback()
    await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.commit()


@pytest.mark.asyncio
async def test_client_turn_recovers_terminal_run_after_cache_gap_expiry_and_cache_deletion():
    async with SessionFactory() as session:
        user_id, conversation_id = await seed(session)
        try:
            request = AgentChatRequest(message="记录午饭", client_turn_id=uuid4())
            turns = service(session)
            decision = await turns.begin(user_id=user_id, request=request)
            run, response = await terminal_run(session, user_id, conversation_id, request, decision)
            # The HTTP handler crashed after durable run success, before caching its response.
            replay = await turns.begin(user_id=user_id, request=request)
            assert (
                replay.replayed and replay.replay_run.id == run.id and replay.response == response
            )
            row = await session.get(IdempotencyRecord, decision.record_id)
            assert row.status == "completed"
            # A reconnect's cache recovery and the original handler's completion can race safely.
            await turns.complete(decision=decision, response=response, run=run)
            await session.execute(
                update(IdempotencyRecord)
                .where(IdempotencyRecord.id == decision.record_id)
                .values(expires_at=datetime.now(UTC) - timedelta(days=2))
            )
            await session.commit()
            assert (await turns.begin(user_id=user_id, request=request)).response == response
            await session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.id == decision.record_id)
            )
            await session.commit()
            replay = await turns.begin(user_id=user_id, request=request)
            assert replay.replayed and replay.record_id is None and replay.response == response
            with pytest.raises(IdempotencyKeyConflictError):
                await turns.begin(
                    user_id=user_id, request=request.model_copy(update={"message": "不同内容"})
                )
        finally:
            await cleanup(session, [user_id])


@pytest.mark.asyncio
async def test_client_turn_duplicate_claims_are_fenced_and_new_key_remains_new_intent():
    async with SessionFactory() as seed_session:
        user_id, conversation_id = await seed(seed_session)
    try:
        request = AgentChatRequest(
            message="生成训练草稿", conversation_id=conversation_id, client_turn_id=uuid4()
        )
        async with SessionFactory() as first, SessionFactory() as second:
            results = await asyncio.gather(
                service(first).begin(user_id=user_id, request=request),
                service(second).begin(user_id=user_id, request=request),
                return_exceptions=True,
            )
            acquired = [result for result in results if not isinstance(result, Exception)]
            errors = [result for result in results if isinstance(result, Exception)]
            assert len(acquired) == 1 and not acquired[0].replayed
            assert len(errors) == 1 and isinstance(errors[0], IdempotencyRequestInProgressError)
        async with SessionFactory() as session:
            turns = service(session)
            with pytest.raises(IdempotencyKeyConflictError):
                await turns.begin(
                    user_id=user_id, request=request.model_copy(update={"message": "不同内容"})
                )
            new = await turns.begin(
                user_id=user_id, request=request.model_copy(update={"client_turn_id": uuid4()})
            )
            assert not new.replayed and new.record_id != acquired[0].record_id
    finally:
        async with SessionFactory() as session:
            await cleanup(session, [user_id])


@pytest.mark.asyncio
async def test_client_turn_identity_is_user_scoped_and_original_request_hash_is_preserved():
    async with SessionFactory() as session:
        user_id, conversation_id = await seed(session)
        foreign_id, _ = await seed(session)
        try:
            request = AgentChatRequest(message="查询热量", client_turn_id=uuid4())
            turns = service(session)
            decision = await turns.begin(user_id=user_id, request=request)
            foreign = await turns.begin(user_id=foreign_id, request=request)
            assert foreign.record_id != decision.record_id and not foreign.replayed
            run, _ = await terminal_run(session, user_id, conversation_id, request, decision)
            assert run.checkpoint["client_request_hash"] == decision.request_hash
            assert run.request_payload["conversation_id"] == str(conversation_id)
            assert (await turns.begin(user_id=user_id, request=request)).replayed
        finally:
            await cleanup(session, [user_id, foreign_id])


@pytest.mark.asyncio
async def test_failed_run_and_pre_run_failure_never_reexecute_same_action():
    async with SessionFactory() as session:
        user_id, conversation_id = await seed(session)
        try:
            turns = service(session)
            request = AgentChatRequest(message="测试中断", client_turn_id=uuid4())
            decision = await turns.begin(user_id=user_id, request=request)
            run, _ = await terminal_run(session, user_id, conversation_id, request, decision)
            run_id = run.id
            run.status, run.result_payload = "failed", None
            await session.commit()
            with pytest.raises(AgentTurnReplayError):
                await turns.begin(user_id=user_id, request=request)
            await turns.fail(
                decision=decision,
                run=await session.get(AgentRun, run_id),
                error_code="AGENT_TIMEOUT",
                error_message="private provider details",
            )
            with pytest.raises(AgentTurnReplayError):
                await turns.begin(user_id=user_id, request=request)
            before_run = AgentChatRequest(message="启动失败", client_turn_id=uuid4())
            before_decision = await turns.begin(user_id=user_id, request=before_run)
            await turns.fail(decision=before_decision, error_code="AGENT_START_FAILED")
            with pytest.raises(AgentTurnReplayError) as caught:
                await turns.begin(user_id=user_id, request=before_run)
            assert caught.value.error_code == "AGENT_START_FAILED"
            row = await session.get(IdempotencyRecord, decision.record_id)
            assert "private provider details" not in str(row.response_body)
        finally:
            await cleanup(session, [user_id])


@pytest.mark.asyncio
async def test_running_replay_exposes_original_run_id_and_stale_startup_reports_unknown():
    async with SessionFactory() as session:
        user_id, conversation_id = await seed(session)
        try:
            turns = service(session)
            request = AgentChatRequest(message="等待工具", client_turn_id=uuid4())
            decision = await turns.begin(user_id=user_id, request=request)
            run, _ = await terminal_run(session, user_id, conversation_id, request, decision)
            run_id = run.id
            run.status, run.result_payload = "running", None
            await session.commit()
            with pytest.raises(IdempotencyRequestInProgressError) as caught:
                await turns.begin(user_id=user_id, request=request)
            assert caught.value.run_id == run_id
            unknown_request = AgentChatRequest(message="启动失联", client_turn_id=uuid4())
            unknown = await turns.begin(user_id=user_id, request=unknown_request)
            await session.execute(
                update(IdempotencyRecord)
                .where(IdempotencyRecord.id == unknown.record_id)
                .values(created_at=datetime.now(UTC) - timedelta(minutes=5))
            )
            await session.commit()
            with pytest.raises(AgentTurnReplayError) as caught:
                await turns.begin(user_id=user_id, request=unknown_request)
            assert caught.value.error_code == "AGENT_TURN_NOT_STARTED"
        finally:
            await cleanup(session, [user_id])


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_cache", [False, True])
async def test_stale_running_same_key_is_fenced_without_reexecution(delete_cache):
    async with SessionFactory() as session:
        user_id, conversation_id = await seed(session)
        try:
            turns = service(session)
            request = AgentChatRequest(message="中断后恢复", client_turn_id=uuid4())
            decision = await turns.begin(user_id=user_id, request=request)
            run, _ = await terminal_run(session, user_id, conversation_id, request, decision)
            run_id = run.id
            run.status, run.result_payload = "running", None
            run.started_at = datetime.now(UTC) - timedelta(minutes=15)
            run.checkpoint = {**run.checkpoint, "safe_marker": "keep"}
            if delete_cache:
                await session.execute(
                    delete(IdempotencyRecord).where(IdempotencyRecord.id == decision.record_id)
                )
            await session.commit()
            with pytest.raises(AgentTurnReplayError) as caught:
                await turns.begin(user_id=user_id, request=request)
            assert caught.value.run_id == run_id
            actual = await session.get(AgentRun, run_id)
            assert actual.status == "failed" and actual.error_code == "AGENT_RUN_INTERRUPTED"
            assert actual.checkpoint["safe_marker"] == "keep"
            with pytest.raises(AgentRunCancelledError):
                await AgentRunService(SqlAlchemyAgentRunRepository(session)).succeed(
                    run=actual, result_payload={"message": "late success"}
                )
            assert (
                len(
                    list(await session.scalars(select(AgentRun).where(AgentRun.user_id == user_id)))
                )
                == 1
            )
        finally:
            await cleanup(session, [user_id])
