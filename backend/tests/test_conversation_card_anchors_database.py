import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import AgentConversation, AgentMessage, AgentRun, Confirmation, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.services.conversation import ConversationService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_cards_stay_with_original_reply_after_resume_and_editor_replacement():
    async with SessionFactory() as session:
        try:
            user = User(username=f"card-anchor-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            conversation = AgentConversation(user_id=user.id)
            session.add(conversation)
            await session.flush()
            start = datetime.now(UTC) - timedelta(minutes=10)
            for sequence in range(1, 7):
                session.add(
                    AgentMessage(
                        conversation_id=conversation.id,
                        sequence=sequence,
                        role="user" if sequence % 2 else "assistant",
                        content=f"正文{sequence}",
                        created_at=start + timedelta(seconds=sequence),
                    )
                )
            cards = [
                Confirmation(
                    user_id=user.id,
                    operation_type="body_measurement_create",
                    after={"measurement": {"weight_kg": "70"}},
                    reason="test",
                    impact="test",
                    status=status,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
                for status in ("succeeded", "cancelled", "pending")
            ]
            session.add_all(cards)
            await session.flush()
            cards[2].after = {**cards[2].after, "replaces_confirmation_id": str(cards[1].id)}
            for offset, refs in [(1.5, [cards[0]]), (3.5, [cards[1]]), (5.5, cards[:2])]:
                session.add(
                    AgentRun(
                        user_id=user.id,
                        conversation_id=conversation.id,
                        status="succeeded",
                        request_payload={},
                        started_at=start + timedelta(seconds=offset),
                        result_payload={
                            "confirmation_cards": [{"confirmation_id": str(c.id)} for c in refs]
                        },
                    )
                )
            await session.flush()
            snapshot = await ConversationService(
                SqlAlchemyConversationRepository(session)
            ).restore_confirmations(
                user_id=user.id,
                conversation_id=conversation.id,
            )
            assert snapshot.completed_cards[0].message_sequence == 2
            assert snapshot.confirmation_cards[0].confirmation_id == cards[2].id
            assert snapshot.confirmation_cards[0].message_sequence == 4
            assert snapshot.completed_cards[0].after == cards[0].after
        finally:
            await session.rollback()
