from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentChatRequest
from nxtrep_backend.services.agent_turn import AgentTurnReplayError, AgentTurnService
from nxtrep_backend.services.idempotency import IdempotencyRequestInProgressError


@pytest.mark.asyncio
async def test_legacy_request_does_not_touch_idempotency_or_run_storage():
    session = MagicMock()
    session.scalar = AsyncMock()
    runs = SimpleNamespace(session=session, get_owned_by_client_turn=AsyncMock())
    service = AgentTurnService(SimpleNamespace(), runs)
    decision = await service.begin(user_id=uuid4(), request=AgentChatRequest(message="你好"))
    assert decision.record_id is None and not decision.replayed
    session.scalar.assert_not_awaited()
    runs.get_owned_by_client_turn.assert_not_awaited()


@pytest.mark.parametrize("status", ["running", "cancel_requested"])
def test_running_action_is_not_reexecuted_or_reported_as_success(status):
    with pytest.raises(IdempotencyRequestInProgressError):
        AgentTurnService._response_from_run(SimpleNamespace(id=uuid4(), status=status))


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_action_without_result_returns_public_safe_replay_error(status):
    with pytest.raises(AgentTurnReplayError) as caught:
        AgentTurnService._response_from_run(
            SimpleNamespace(
                id=uuid4(), status=status, result_payload=None, error_message="provider secret"
            )
        )
    assert "provider secret" not in str(caught.value)
    assert caught.value.status_code == 409


def test_corrupt_final_result_does_not_fake_replay_success():
    with pytest.raises(AgentTurnReplayError) as caught:
        AgentTurnService._response_from_run(
            SimpleNamespace(id=uuid4(), status="succeeded", result_payload={"message": "done"})
        )
    assert caught.value.error_code == "AGENT_RESULT_INVALID"


def test_wrong_conversation_or_run_result_is_not_replayed():
    with pytest.raises(AgentTurnReplayError):
        AgentTurnService._response_from_run(
            SimpleNamespace(
                id=uuid4(),
                conversation_id=uuid4(),
                status="succeeded",
                result_payload={
                    "message": "错会话回复",
                    "conversation_id": str(uuid4()),
                    "run_id": str(uuid4()),
                },
            )
        )
