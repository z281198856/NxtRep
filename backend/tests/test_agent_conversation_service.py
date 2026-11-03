from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import AgentConversation
from nxtrep_backend.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from nxtrep_backend.services.conversation import (
    AgentConversationNotFoundError,
    ConversationService,
    ConversationSummarizer,
)


def make_repository() -> MagicMock:
    repository = MagicMock(spec=SqlAlchemyConversationRepository)
    repository.add_conversation = AsyncMock()
    repository.get_for_user = AsyncMock()
    repository.append_message = AsyncMock()
    repository.list_recent = AsyncMock(return_value=[])
    repository.list_unsummarized = AsyncMock(return_value=[])
    repository.list_conversation_confirmations = AsyncMock(return_value=[])
    repository.flush = AsyncMock()
    return repository


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "succeeded", "cancelled", "expired"])
async def test_meal_context_uses_current_command_state_over_old_pending_reply(status):
    from datetime import timedelta

    user_id, conversation_id, entry_id = uuid4(), uuid4(), uuid4()
    repository = make_repository()
    repository.get_for_user.return_value = AgentConversation(
        id=conversation_id, user_id=user_id, next_sequence=3
    )
    repository.list_recent.return_value = [
        SimpleNamespace(role="assistant", content="已创建午餐草稿，等待确认。")
    ]
    card = SimpleNamespace(
        id=uuid4(),
        status="pending" if status == "expired" else status,
        operation_type="nutrition_entry_create",
        after={
            "entry": {
                "meal_type": "lunch",
                "eaten_at": "2026-10-07T12:30:00+08:00",
                "items": [{"name": "熟米饭", "amount_g": "200"}],
            }
        },
        result={"resource_id": str(entry_id)} if status == "succeeded" else None,
        expires_at=datetime.now(UTC) + timedelta(hours=-1 if status == "expired" else 1),
    )
    repository.list_conversation_confirmations.return_value = [card]
    _, context = await ConversationService(repository).begin_turn(
        user_id=user_id,
        conversation_id=conversation_id,
        user_message="米饭约两百五十克",
        image_asset_ids=[],
    )
    assert context.recent_messages[0].content == "已创建午餐草稿，等待确认。"
    assert context.meal_confirmations[0]["status"] == status
    assert context.meal_confirmations[0]["entry_id"] == (
        str(entry_id) if status == "succeeded" else None
    )
    assert context.as_dict()["meal_confirmations"][0]["foods"] == [
        {"name": "熟米饭", "amount_g": "200"}
    ]
    repository.list_conversation_confirmations.assert_awaited_once_with(
        user_id=user_id, conversation_id=conversation_id
    )


@pytest.mark.asyncio
async def test_create_conversation_adds_an_empty_user_scoped_conversation() -> None:
    user_id = uuid4()
    repository = make_repository()
    repository.add_conversation.side_effect = lambda item: item

    result = await ConversationService(repository).create_conversation(
        user_id=user_id,
        title="新的训练讨论",
    )

    assert result.user_id == user_id
    assert result.title == "新的训练讨论"
    assert result.next_sequence is None
    repository.add_conversation.assert_awaited_once()


@pytest.mark.asyncio
async def test_begin_turn_restores_history_and_appends_current_user_message() -> None:
    user_id = uuid4()
    conversation = AgentConversation(id=uuid4(), user_id=user_id, next_sequence=3)
    repository = make_repository()
    repository.get_for_user.return_value = conversation
    repository.list_recent.return_value = [
        SimpleNamespace(role="user", content="我每周练三天"),
        SimpleNamespace(role="assistant", content="好的"),
    ]
    service = ConversationService(repository)

    result_conversation, context = await service.begin_turn(
        user_id=user_id,
        conversation_id=conversation.id,
        user_message="那帮我安排一下",
        image_asset_ids=[],
    )

    assert result_conversation is conversation
    assert [item.content for item in context.recent_messages] == [
        "我每周练三天",
        "好的",
    ]
    repository.get_for_user.assert_awaited_once_with(
        user_id=user_id,
        conversation_id=conversation.id,
        lock=True,
    )
    repository.append_message.assert_awaited_once_with(
        conversation=conversation,
        role="user",
        content="那帮我安排一下",
        image_asset_ids=[],
    )


@pytest.mark.asyncio
async def test_begin_turn_rejects_unknown_or_other_users_conversation() -> None:
    repository = make_repository()
    repository.get_for_user.return_value = None
    service = ConversationService(repository)

    with pytest.raises(AgentConversationNotFoundError):
        await service.begin_turn(
            user_id=uuid4(),
            conversation_id=uuid4(),
            user_message="继续",
            image_asset_ids=[],
        )

    repository.append_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_turn_is_rejected_under_conversation_lock_before_any_message_or_summary():
    repository = make_repository()
    user_id = uuid4()
    conversation = AgentConversation(id=uuid4(), user_id=user_id, next_sequence=3)
    repository.get_for_user.return_value = conversation
    guard = AsyncMock(side_effect=RuntimeError("conversation busy"))
    service = ConversationService(repository, turn_guard=guard)

    with pytest.raises(RuntimeError, match="conversation busy"):
        await service.begin_turn(
            user_id=user_id,
            conversation_id=conversation.id,
            user_message="同一会话的第二条请求",
            image_asset_ids=[],
        )

    repository.get_for_user.assert_awaited_once_with(
        user_id=user_id, conversation_id=conversation.id, lock=True,
    )
    guard.assert_awaited_once_with(user_id, conversation.id)
    repository.list_unsummarized.assert_not_awaited()
    repository.append_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_finish_turn_relocks_fresh_conversation_before_appending_assistant():
    repository = make_repository()
    user_id, conversation_id = uuid4(), uuid4()
    stale = AgentConversation(id=conversation_id, user_id=user_id, next_sequence=3)
    fresh = AgentConversation(id=conversation_id, user_id=user_id, next_sequence=5)
    repository.get_for_user.return_value = fresh

    await ConversationService(repository).finish_turn(
        conversation=stale, assistant_message="  本轮结果  ",
    )

    repository.get_for_user.assert_awaited_once_with(
        user_id=user_id, conversation_id=conversation_id, lock=True, active_only=False,
    )
    repository.append_message.assert_awaited_once_with(
        conversation=fresh, role="assistant", content="本轮结果",
    )


@pytest.mark.asyncio
async def test_old_messages_are_incrementally_summarized_but_recent_messages_remain() -> None:
    user_id = uuid4()
    conversation = AgentConversation(
        id=uuid4(),
        user_id=user_id,
        summary="旧摘要",
        summary_through_sequence=4,
        next_sequence=26,
        version=1,
        last_message_at=datetime(2026, 9, 3, tzinfo=UTC),
    )
    messages = [
        SimpleNamespace(sequence=index, role="user", content=f"消息 {index}")
        for index in range(5, 26)
    ]
    repository = make_repository()
    repository.get_for_user.return_value = conversation
    repository.list_unsummarized.return_value = messages
    repository.list_recent.return_value = messages[-12:]
    summarizer = MagicMock(spec=ConversationSummarizer)
    summarizer.summarize = AsyncMock(return_value="新摘要")
    service = ConversationService(repository, summarizer)

    _conversation, context = await service.begin_turn(
        user_id=user_id,
        conversation_id=conversation.id,
        user_message="继续",
        image_asset_ids=[],
    )

    assert conversation.summary == "新摘要"
    assert conversation.summary_through_sequence == 13
    assert context.summary == "新摘要"
    assert len(context.recent_messages) == 12
    summarizer.summarize.assert_awaited_once_with(
        previous_summary="旧摘要",
        messages=messages[:9],
    )
    repository.flush.assert_awaited_once()
