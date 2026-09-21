from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import AgentRun
from nxtrep_backend.repositories.agent_run import SqlAlchemyAgentRunRepository
from nxtrep_backend.services.agent_run import AgentRunCancelledError, AgentRunService


def make_repository() -> MagicMock:
    repository = MagicMock(spec=SqlAlchemyAgentRunRepository)
    repository.add = AsyncMock(side_effect=lambda item: item)
    repository.refresh = AsyncMock()
    repository.flush = AsyncMock()
    repository.commit = AsyncMock()
    return repository


@pytest.mark.asyncio
async def test_run_start_is_committed_so_polling_can_see_it() -> None:
    repository = make_repository()

    run = await AgentRunService(repository).start(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={"message": "hello"},
    )

    assert run.status == "running"
    assert run.checkpoint == {"node": "started"}
    repository.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_checkpoint_turns_cancel_request_into_cancelled_run() -> None:
    repository = make_repository()
    run = AgentRun(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="cancel_requested",
        version=1,
    )

    with pytest.raises(AgentRunCancelledError):
        await AgentRunService(repository).checkpoint(run=run, node="execute_branches")

    assert run.status == "cancelled"
    assert run.finished_at is not None
    repository.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_cancelled_refreshes_running_run_without_writing() -> None:
    repository = make_repository()
    run = AgentRun(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="running",
        version=1,
    )

    result = await AgentRunService(repository).check_cancelled(run=run)

    assert result is run
    repository.refresh.assert_awaited_once_with(run)
    repository.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_cancelled_rejects_already_cancelled_run_without_writing() -> None:
    repository = make_repository()
    run = AgentRun(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="cancelled",
        version=2,
    )

    with pytest.raises(AgentRunCancelledError):
        await AgentRunService(repository).check_cancelled(run=run)

    repository.refresh.assert_awaited_once_with(run)
    repository.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_abort_marks_non_terminal_stream_run_cancelled() -> None:
    repository = make_repository()
    run = AgentRun(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="running",
        version=3,
    )

    result = await AgentRunService(repository).abort(
        run=run,
        reason="Agent stream consumer disconnected",
    )

    assert result.status == "cancelled"
    assert result.error_code == "AGENT_STREAM_CLOSED"
    assert result.checkpoint["node"] == "stream_closed"
    assert result.finished_at is not None
    assert result.version == 4
    repository.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_abort_does_not_overwrite_terminal_run() -> None:
    repository = make_repository()
    run = AgentRun(
        user_id=uuid4(),
        conversation_id=uuid4(),
        request_payload={},
        status="succeeded",
        version=4,
    )

    result = await AgentRunService(repository).abort(run=run, reason="late disconnect")

    assert result.status == "succeeded"
    assert result.version == 4
    repository.commit.assert_not_awaited()
