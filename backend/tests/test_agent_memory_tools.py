from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.memory import (
    MemoryScopeMatch,
    build_memory_read_tools,
    build_memory_write_tools,
)
from nxtrep_backend.schemas.agent import AgentMemoryInstruction
from nxtrep_backend.services.memory import MemoryService


def make_memory(*, category: str, content: str, version: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        category=category,
        content=content,
        confirmed_at=datetime(2026, 9, 3, tzinfo=UTC),
        deleted_at=None,
        version=version,
    )


def make_context() -> MagicMock:
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    context.memory_scope = None
    context.memory_scope_model = None
    context.memory_service = MagicMock(spec=MemoryService)
    context.memory_service.list_memories = AsyncMock()
    context.memory_service.create = AsyncMock()
    context.memory_service.update = AsyncMock()
    context.memory_service.delete = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_read_memory_tool_binds_authenticated_user() -> None:
    context = make_context()
    memory = make_memory(category="equipment", content="家里只有一对可调哑铃")
    context.memory_service.list_memories.return_value = [memory]
    current_tool = build_memory_read_tools(context)[0]

    result = await current_tool.ainvoke({"category": "equipment", "limit": 10})

    assert result["status"] == "available"
    assert result["memories"][0]["content"] == memory.content
    context.memory_service.list_memories.assert_awaited_once_with(
        user_id=context.user_id,
        category="equipment",
        limit=10,
    )
    assert "user_id" not in current_tool.args


@pytest.mark.asyncio
async def test_save_memory_tool_writes_directly() -> None:
    context = make_context()
    memory = make_memory(category="allergy", content="花生过敏")
    context.memory_service.create.return_value = memory
    current_tool = build_memory_write_tools(context)[0]

    result = await current_tool.ainvoke({"category": "allergy", "content": "花生过敏"})

    assert result["status"] == "saved"
    assert result["memory"]["id"] == str(memory.id)
    context.memory_service.create.assert_awaited_once_with(
        user_id=context.user_id,
        category="allergy",
        content="花生过敏",
    )


@pytest.mark.asyncio
async def test_update_memory_tool_binds_user_and_version() -> None:
    context = make_context()
    memory = make_memory(category="equipment", content="现在有杠铃和深蹲架", version=3)
    context.memory_service.update.return_value = memory
    current_tool = build_memory_write_tools(context)[1]
    memory_id = uuid4()

    result = await current_tool.ainvoke(
        {
            "memory_id": str(memory_id),
            "expected_version": 2,
            "category": "equipment",
            "content": "现在有杠铃和深蹲架",
        }
    )

    assert result["status"] == "updated"
    assert result["memory"]["version"] == 3
    context.memory_service.update.assert_awaited_once_with(
        user_id=context.user_id,
        memory_id=memory_id,
        expected_version=2,
        category="equipment",
        content="现在有杠铃和深蹲架",
    )


@pytest.mark.asyncio
async def test_delete_memory_tool_binds_user_and_version() -> None:
    context = make_context()
    memory = make_memory(category="schedule", content="周末训练", version=4)
    memory.deleted_at = datetime(2026, 9, 4, tzinfo=UTC)
    context.memory_service.delete.return_value = memory
    current_tool = build_memory_write_tools(context)[2]
    memory_id = uuid4()

    result = await current_tool.ainvoke({"memory_id": str(memory_id), "expected_version": 3})

    assert result["status"] == "deleted"
    assert result["memory_id"] == str(memory.id)
    context.memory_service.delete.assert_awaited_once_with(
        user_id=context.user_id,
        memory_id=memory_id,
        expected_version=3,
    )


@pytest.mark.asyncio
async def test_scoped_memory_cannot_save_business_request_from_mixed_message():
    context = make_context()
    context.memory_scope = (
        AgentMemoryInstruction(
            action="save",
            category="dietary_preference",
            content="不吃香菜",
            evidence="我不吃香菜",
        ),
    )
    context.memory_service.create.return_value = make_memory(
        category="dietary_preference",
        content="不吃香菜",
    )
    save = build_memory_write_tools(context)[0]
    denied = await save.ainvoke({"category": "other", "content": "把汉堡添加到食品库"})
    assert denied["status"] == "not_saved"
    context.memory_service.create.assert_not_awaited()
    allowed = await save.ainvoke({"category": "dietary_preference", "content": "不吃香菜"})
    assert allowed["status"] == "saved"


@pytest.mark.asyncio
async def test_scoped_memory_cannot_delete_unrelated_fact():
    context = make_context()
    existing = make_memory(category="allergy", content="花生过敏")
    context.memory_service.list_memories.return_value = [existing]
    context.memory_scope = (
        AgentMemoryInstruction(
            action="delete",
            category="equipment",
            content="只有哑铃",
            evidence="现在不再只有哑铃了",
        ),
    )
    result = await build_memory_write_tools(context)[2].ainvoke(
        {
            "memory_id": str(existing.id),
            "expected_version": 1,
        }
    )
    assert result["status"] == "not_saved"
    context.memory_service.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("matched", [True, False])
async def test_retraction_semantically_matches_target_without_deleting_other_fact(matched):
    context = make_context()
    existing = make_memory(category="equipment", content="家里只有杠铃，没有哑铃")
    context.memory_service.list_memories.return_value = [existing]
    context.memory_service.delete.return_value = existing
    existing.deleted_at = datetime.now(UTC)
    context.memory_scope = (
        AgentMemoryInstruction(
            action="delete",
            category="equipment",
            content="家中仅有杠铃",
            evidence="忘记家中仅有杠铃的器械限制",
        ),
    )
    context.memory_scope_model = MagicMock()
    structured = context.memory_scope_model.with_structured_output.return_value
    structured.ainvoke = AsyncMock(
        return_value={
            "parsed": MemoryScopeMatch(
                matched=matched,
                reason="Same requested fact" if matched else "Different equipment fact",
            )
        }
    )
    result = await build_memory_write_tools(context)[2].ainvoke(
        {
            "memory_id": str(existing.id),
            "expected_version": 1,
        }
    )
    assert result["status"] == ("deleted" if matched else "not_saved")
    assert context.memory_service.delete.await_count == int(matched)
