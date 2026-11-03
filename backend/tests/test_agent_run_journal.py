from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.schemas.agent import AgentBranchError, AgentBranchResult, AgentChatRequest
from nxtrep_backend.services.agent_run import AgentRunCancelledError, AgentRunService
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.conversation import AgentConversationContext, ConversationService


def repository():
    value = MagicMock(spec=SqlAlchemyAgentRunRepository)
    value.add = AsyncMock(side_effect=lambda item: item)
    value.refresh = AsyncMock()
    value.refresh_locked = AsyncMock()
    value.commit = AsyncMock()
    value.flush = AsyncMock()
    value.rollback = AsyncMock()
    value.lock_conversation = AsyncMock(return_value=True)
    value.list_active = AsyncMock(return_value=[])
    value.existing_confirmation_refs = AsyncMock(side_effect=lambda _user, refs: set(refs))
    return value


def running(**overrides):
    return AgentRun(
        id=uuid4(),
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="running",
        version=1,
        started_at=datetime.now(UTC),
        checkpoint={"node": "execute_branches", "confirmation_refs": []},
        **overrides,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["succeed", "fail", "abort"])
async def test_terminal_status_preserves_recoverable_confirmation_refs(terminal):
    repo = repository()
    ref = str(uuid4())
    run = running()
    run.checkpoint["confirmation_refs"] = [ref]
    service = AgentRunService(repo)
    if terminal == "succeed":
        await service.succeed(run=run, result_payload={"status": "completed"})
    elif terminal == "fail":
        await service.fail(run=run, error_code="SYNTHESIS_FAILED", error_message="未生成回答")
    else:
        await service.abort(run=run, reason="Agent stream consumer disconnected")
    assert run.checkpoint["confirmation_refs"] == [ref]


@pytest.mark.asyncio
async def test_cancelled_checkpoint_preserves_tool_journal_from_this_node():
    repo = repository()
    run = running()
    run.status = "cancel_requested"
    ref = str(uuid4())
    with pytest.raises(AgentRunCancelledError):
        await AgentRunService(repo).checkpoint(
            run=run,
            node="execute_branches",
            journal={"confirmation_refs": [ref]},
        )
    assert run.checkpoint["confirmation_refs"] == [ref]
    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_superseded_run_cannot_overwrite_terminal_state_with_success():
    repo = repository()
    run = running()
    run.status = "failed"
    run.error_code = "AGENT_RUN_INTERRUPTED"
    with pytest.raises(AgentRunCancelledError):
        await AgentRunService(repo).succeed(run=run, result_payload={"status": "completed"})
    assert run.status == "failed" and run.error_code == "AGENT_RUN_INTERRUPTED"
    repo.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_run_claim_rejects_second_turn_and_does_not_add_run():
    repo = repository()
    repo.lock_conversation = AsyncMock(return_value=True)
    active = running()
    repo.list_active = AsyncMock(return_value=[active])
    repo.rollback = AsyncMock()
    from nxtrep_backend.services.agent_run import AgentRunInProgressError

    with pytest.raises(AgentRunInProgressError):
        await AgentRunService(repo).start(
            user_id=active.user_id,
            conversation_id=active.conversation_id,
            request_payload={},
        )
    repo.add.assert_not_awaited()
    repo.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_run_closes_before_new_claim_and_keeps_old_refs():
    repo = repository()
    repo.lock_conversation = AsyncMock(return_value=True)
    active = running()
    active.started_at = datetime.now(UTC) - timedelta(minutes=15)
    ref = str(uuid4())
    active.checkpoint["confirmation_refs"] = [ref]
    repo.list_active = AsyncMock(return_value=[active])
    await AgentRunService(repo, stale_after_seconds=600).ensure_available(
        active.user_id,
        active.conversation_id,
    )
    assert active.status == "failed" and active.error_code == "AGENT_RUN_INTERRUPTED"
    assert active.checkpoint["confirmation_refs"] == [ref]
    assert active.finished_at is not None
    repo.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_checkpoint_merges_new_refs_instead_of_replacing_previous_refs():
    repo = repository()
    run = running()
    previous, current = str(uuid4()), str(uuid4())
    run.checkpoint["confirmation_refs"] = [previous]
    await AgentRunService(repo).checkpoint(
        run=run,
        node="validate_execution",
        journal={"confirmation_refs": [current, previous, "not-a-uuid"]},
    )
    assert run.checkpoint["confirmation_refs"] == [previous, current]
    assert run.checkpoint["node"] == "validate_execution"


@pytest.mark.asyncio
async def test_rollback_refs_and_foreign_refs_are_not_written_as_recoverable():
    repo = repository()
    owned, rolled_back, foreign = uuid4(), uuid4(), uuid4()
    repo.existing_confirmation_refs = AsyncMock(return_value={owned})
    run = running()
    await AgentRunService(repo).fail(
        run=run,
        error_code="AGENT_TIMEOUT",
        error_message="处理超时",
        journal={"confirmation_refs": [str(owned), str(rolled_back), str(foreign)]},
    )
    assert run.checkpoint["confirmation_refs"] == [str(owned)]
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_journal_does_not_persist_full_arguments_results_or_private_text():
    repo = repository()
    run = running()
    record = {
        "tool_name": "propose_food",
        "status": "unknown",
        "duration_ms": 21,
        "tool_call_id": str(uuid4()),
        "argument_fingerprint": "123abc",
        "arguments": {"private": "not-for-log"},
        "result": {"full": "payload"},
        "message": "私密用户文字",
    }
    await AgentRunService(repo).fail(
        run=run,
        error_code="AGENT_TIMEOUT",
        error_message="处理超时",
        journal={"tool_runs": [record], "operations": [record], "unknown_operations": [record]},
    )
    for field in ("tool_runs", "operations", "unknown_operations"):
        saved = run.checkpoint[field][0]
        assert "arguments" not in saved and "result" not in saved and "message" not in saved
        assert saved["tool_call_id"] == record["tool_call_id"]


def workflow(graph, *, journal=None):
    repo = repository()
    run = running()
    repo.add = AsyncMock(return_value=run)
    conversations = MagicMock(spec=ConversationService)
    from types import SimpleNamespace

    conversations.begin_turn = AsyncMock(
        return_value=(
            SimpleNamespace(id=run.conversation_id),
            AgentConversationContext(),
        )
    )
    conversations.finish_turn = AsyncMock()
    return (
        AgentWorkflowService(
            graph,
            conversations,
            AgentRunService(repo),
            tool_journal_provider=(lambda: journal) if journal is not None else None,
        ),
        run,
        repo,
        conversations,
    )


@pytest.mark.asyncio
async def test_workflow_error_after_proposal_keeps_journal_without_fake_success():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=RuntimeError("response generation failed"))
    ref = str(uuid4())
    service, run, _, conversations = workflow(graph, journal={"confirmation_refs": [ref]})
    with pytest.raises(RuntimeError, match="response generation"):
        await service.chat(user_id=run.user_id, request=AgentChatRequest(message="修改这餐"))
    assert run.status == "failed" and run.result_payload is None
    assert run.checkpoint["confirmation_refs"] == [ref]
    conversations.finish_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_dedicated_branch_proposal_survives_later_synthesis_failure():
    from nxtrep_backend.schemas.agent import AgentConfirmationCard, AgentExecutionBundle

    ref = uuid4()
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="nutrition_record_draft",
                status="completed",
                result={"draft": True},
                requires_confirmation=True,
                confirmation_cards=[
                    AgentConfirmationCard(
                        confirmation_id=ref,
                        operation_type="nutrition_entry_create",
                        status="pending",
                        impact="确认后保存",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                        version=1,
                    )
                ],
            )
        ]
    )

    async def updates(*_args, **_kwargs):
        yield ("updates", {"execute_branches": {"execution_bundle": bundle}})
        raise RuntimeError("synthesis unavailable")

    graph = MagicMock()
    graph.astream.side_effect = updates
    service, run, _, conversations = workflow(graph)
    events = [
        event
        async for event in service.stream(
            user_id=run.user_id,
            request=AgentChatRequest(message="记这餐"),
        )
    ]
    assert events[-1].event == "failed" and run.status == "failed"
    assert run.checkpoint["confirmation_refs"] == [str(ref)]
    assert run.result_payload is None
    conversations.finish_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_internal_branch_still_persists_created_proposal_refs():
    from nxtrep_backend.schemas.agent import AgentExecutionBundle

    ref = str(uuid4())
    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "response_message": "草稿已生成，但后续处理失败，请核对待确认草稿。",
            "execution_bundle": AgentExecutionBundle(
                branch_results=[
                    AgentBranchResult(
                        task_type="nutrition_entry_update_draft",
                        status="failed",
                        error=AgentBranchError(
                            code="SAVED_MEAL_DRAFT_NOT_CREATED", message="未完成", retryable=True
                        ),
                    )
                ]
            ),
        }
    )
    service, run, _, _ = workflow(graph, journal={"confirmation_refs": [ref]})
    response = await service.chat(
        user_id=run.user_id, request=AgentChatRequest(message="米饭100克")
    )
    assert response.status == "failed" and run.status == "failed"
    assert run.checkpoint["confirmation_refs"] == [ref]
    assert run.result_payload["status"] == "failed"


@pytest.mark.asyncio
async def test_stream_disconnect_keeps_proposals_already_generated_in_this_turn():
    async def updates(*_args, **_kwargs):
        yield ("updates", {"execute_branches": {}})

    graph = MagicMock()
    graph.astream.side_effect = updates
    ref = str(uuid4())
    service, run, _, conversations = workflow(graph, journal={"confirmation_refs": [ref]})
    stream = service.stream(user_id=run.user_id, request=AgentChatRequest(message="改这餐"))
    assert (await anext(stream)).event == "run_started"
    assert (await anext(stream)).event == "node_completed"
    await stream.aclose()
    assert run.status == "cancelled" and run.checkpoint["confirmation_refs"] == [ref]
    assert run.result_payload is None
    conversations.finish_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_at_dedicated_branch_boundary_keeps_just_returned_proposal():
    from nxtrep_backend.schemas.agent import AgentConfirmationCard, AgentExecutionBundle

    ref = uuid4()
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="nutrition_record_draft",
                status="completed",
                result={"draft": True},
                requires_confirmation=True,
                confirmation_cards=[
                    AgentConfirmationCard(
                        confirmation_id=ref,
                        operation_type="nutrition_entry_create",
                        status="pending",
                        impact="确认后保存",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                        version=1,
                    )
                ],
            )
        ]
    )

    async def updates(*_args, **_kwargs):
        run.status = "cancel_requested"
        yield ("updates", {"execute_branches": {"execution_bundle": bundle}})

    graph = MagicMock()
    graph.astream.side_effect = updates
    service, run, _, conversations = workflow(graph)
    events = [
        event
        async for event in service.stream(
            user_id=run.user_id,
            request=AgentChatRequest(message="记这餐"),
        )
    ]
    assert events[-1].event == "cancelled" and run.status == "cancelled"
    assert run.checkpoint["confirmation_refs"] == [str(ref)]
    conversations.finish_turn.assert_not_awaited()
