from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.memory import (
    build_memory_read_tools,
    build_memory_write_tools,
)
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
