from typing import Annotated
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import Field

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.services.memory import MemoryCategory


def _memory_payload(item) -> dict:
    return {
        "id": str(item.id),
        "category": item.category,
        "content": item.content,
        "saved_at": item.confirmed_at.isoformat(),
        "version": item.version,
    }


def build_memory_read_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_memories(
        category: MemoryCategory | None = None,
        limit: int = 20,
    ) -> dict:
        """Read the current user's active long-term facts and preferences."""
        safe_limit = min(max(limit, 1), 50)
        items = await context.memory_service.list_memories(
            user_id=context.user_id,
            category=category,
            limit=safe_limit,
        )
        return {
            "status": "available",
            "memories": [_memory_payload(item) for item in items],
        }

    return [read_memories]


def build_memory_write_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def save_memory(
        category: MemoryCategory,
        content: Annotated[str, Field(min_length=1, max_length=2000)],
    ) -> dict:
        """Directly save a stable user fact or preference and report what was saved."""
        item = await context.memory_service.create(
            user_id=context.user_id,
            category=category,
            content=content,
        )
        return {"status": "saved", "memory": _memory_payload(item)}

    @tool
    async def update_memory(
        memory_id: UUID,
        expected_version: int,
        category: MemoryCategory,
        content: Annotated[str, Field(min_length=1, max_length=2000)],
    ) -> dict:
        """Directly correct an existing Memory after reading its id and version."""
        item = await context.memory_service.update(
            user_id=context.user_id,
            memory_id=memory_id,
            expected_version=expected_version,
            category=category,
            content=content,
        )
        return {"status": "updated", "memory": _memory_payload(item)}

    @tool
    async def delete_memory(
        memory_id: UUID,
        expected_version: int,
    ) -> dict:
        """Directly soft-delete an existing Memory after reading its id and version."""
        item = await context.memory_service.delete(
            user_id=context.user_id,
            memory_id=memory_id,
            expected_version=expected_version,
        )
        return {
            "status": "deleted",
            "memory_id": str(item.id),
            "version": item.version,
            "deleted_at": item.deleted_at.isoformat(),
        }

    return [save_memory, update_memory, delete_memory]
