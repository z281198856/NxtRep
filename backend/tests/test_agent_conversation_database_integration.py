import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from nxtrep_backend.db.models import AgentMessage, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.conversation import (
    SqlAlchemyConversationRepository,
)
from nxtrep_backend.services.conversation import (
    AgentConversationNotFoundError,
    ConversationService,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_conversation_persists_and_restores_user_scoped_history() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            owner = User(
                username=f"conversation-owner-{uuid4().hex}",
                password_setup_required=False,
            )
            other = User(
                username=f"conversation-other-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add_all([owner, other])
            await session.flush()

            service = ConversationService(SqlAlchemyConversationRepository(session))
            conversation, first_context = await service.begin_turn(
                user_id=owner.id,
                conversation_id=None,
                user_message="我每周训练三天",
                image_asset_ids=[],
            )
            assert first_context.recent_messages == ()

            await service.finish_turn(
                conversation=conversation,
                assistant_message="已经了解你的训练频率",
            )

            _same_conversation, second_context = await service.begin_turn(
                user_id=owner.id,
                conversation_id=conversation.id,
                user_message="那帮我安排一下",
                image_asset_ids=[],
            )

            assert [item.content for item in second_context.recent_messages] == [
                "我每周训练三天",
                "已经了解你的训练频率",
            ]
            messages = list(
                await session.scalars(
                    select(AgentMessage)
                    .where(AgentMessage.conversation_id == conversation.id)
                    .order_by(AgentMessage.sequence)
                )
            )
            assert [item.sequence for item in messages] == [1, 2, 3]

            with pytest.raises(AgentConversationNotFoundError):
                await service.begin_turn(
                    user_id=other.id,
                    conversation_id=conversation.id,
                    user_message="读取别人的会话",
                    image_asset_ids=[],
                )
        finally:
            await transaction.rollback()
