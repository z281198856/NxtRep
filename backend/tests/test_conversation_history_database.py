import os
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.db.models import AgentConversation, AgentMessage, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.services.conversation import ConversationService
from nxtrep_backend.services.conversation_title import _refresh_one

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_archive_rename_restore_serializes_updated_at_and_preserves_messages(monkeypatch):
    monkeypatch.setattr(
        "nxtrep_backend.services.conversation_title.schedule_conversation_titles",
        lambda *args: None,
    )
    async with SessionFactory() as session:
        try:
            owner = User(username=f"history-{uuid4().hex}", password_setup_required=False)
            other = User(username=f"history-other-{uuid4().hex}", password_setup_required=False)
            session.add_all([owner, other])
            await session.flush()
            service = ConversationService(SqlAlchemyConversationRepository(session))
            conversation, _ = await service.begin_turn(
                user_id=owner.id,
                conversation_id=None,
                user_message="午饭改到前一天",
                image_asset_ids=[],
            )
            await service.finish_turn(conversation=conversation, assistant_message="请核对这餐。")
            identifier = conversation.id
            original = list(
                await session.scalars(
                    select(AgentMessage.content)
                    .where(AgentMessage.conversation_id == identifier)
                    .order_by(AgentMessage.sequence)
                )
            )

            async def db_override():
                yield session

            app.dependency_overrides[get_db_session] = db_override
            app.dependency_overrides[get_current_user] = lambda: owner
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1/agent"
            ) as client:
                url = f"/conversations/{identifier}"
                request = {"status": "archived", "expected_version": conversation.version}
                archived = await client.patch(url, json=request)
                assert archived.status_code == 200, archived.text
                assert archived.json()["status"] == "archived"
                assert archived.json()["updated_at"]
                assert (await client.patch(url, json=request)).status_code == 409
                assert (await client.get("/conversations", params={"status": "active"})).json()[
                    "list"
                ] == []
                assert (
                    len(
                        (await client.get("/conversations", params={"status": "archived"})).json()[
                            "list"
                        ]
                    )
                    == 1
                )
                renamed = await client.patch(
                    url,
                    json={"title": "我的饮食复盘", "expected_version": archived.json()["version"]},
                )
                assert renamed.status_code == 200, renamed.text
                assert renamed.json()["title_source"] == "manual"
                restored = await client.patch(
                    url, json={"status": "active", "expected_version": renamed.json()["version"]}
                )
                assert restored.status_code == 200, restored.text
                assert restored.json()["title"] == "我的饮食复盘"
                assert (
                    list(
                        await session.scalars(
                            select(AgentMessage.content)
                            .where(AgentMessage.conversation_id == identifier)
                            .order_by(AgentMessage.sequence)
                        )
                    )
                    == original
                )
                app.dependency_overrides[get_current_user] = lambda: other
                assert (
                    await client.patch(
                        url,
                        json={"status": "archived", "expected_version": restored.json()["version"]},
                    )
                ).status_code == 404
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            app.dependency_overrides.pop(get_current_user, None)
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manual_race,model_failure", [(False, False), (True, False), (False, True)]
)
async def test_generated_title_cas_preserves_manual_rename_and_model_failure_falls_back(
    manual_race,
    model_failure,
):
    user_id, conversation_id = uuid4(), uuid4()
    try:
        async with SessionFactory.begin() as session:
            session.add(
                User(id=user_id, username=f"title-{uuid4().hex}", password_setup_required=False)
            )
            await session.flush()
            conversation = AgentConversation(
                id=conversation_id,
                user_id=user_id,
                title_source="fallback",
                title="午饭脂肪偏高",
                next_sequence=3,
            )
            session.add(conversation)
            await session.flush()
            session.add_all(
                [
                    AgentMessage(
                        conversation_id=conversation_id,
                        role="user",
                        content="午饭脂肪偏高，帮我调低一点",
                        sequence=1,
                    ),
                    AgentMessage(
                        conversation_id=conversation_id,
                        role="assistant",
                        content="可以减少烹调油，请核对份量。",
                        sequence=2,
                    ),
                ]
            )

        async def generate(messages):
            assert len(messages) == 2
            if manual_race:
                async with SessionFactory.begin() as session:
                    await session.execute(
                        update(AgentConversation)
                        .where(AgentConversation.id == conversation_id)
                        .values(
                            title="用户亲自取的名字",
                            title_source="manual",
                            version=AgentConversation.version + 1,
                        )
                    )
            if model_failure:
                raise TimeoutError("synthetic title timeout")
            return "午饭份量与脂肪调整"

        titler = AsyncMock()
        titler.generate.side_effect = generate
        await _refresh_one(user_id, conversation_id, titler)
        async with SessionFactory() as session:
            result = await session.get(AgentConversation, conversation_id)
            expected = (
                "用户亲自取的名字"
                if manual_race
                else ("午饭脂肪偏高，帮我调低一点" if model_failure else "午饭份量与脂肪调整")
            )
            assert result.title == expected
            assert result.title_source == (
                "manual" if manual_race else "fallback" if model_failure else "generated"
            )
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
