from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from nxtrep_backend.db.models import AgentMemory
from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository

MemoryCategory = Literal[
    "long_term_goal",
    "equipment",
    "schedule",
    "allergy",
    "dietary_preference",
    "exercise_limit",
    "communication_preference",
    "other",
]


class MemoryNotFoundError(RuntimeError):
    pass


class MemoryConflictError(RuntimeError):
    pass


class MemoryService:
    """Direct long-term Memory writes with ownership and version protection."""

    def __init__(self, repository: SqlAlchemyMemoryRepository) -> None:
        self.repository = repository

    async def list_memories(
        self,
        *,
        user_id: UUID,
        category: MemoryCategory | None = None,
        limit: int = 20,
    ) -> list[AgentMemory]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return await self.repository.list_active(
            user_id=user_id,
            category=category,
            limit=limit,
        )

    async def create(
        self,
        *,
        user_id: UUID,
        category: MemoryCategory,
        content: str,
    ) -> AgentMemory:
        normalized = self._normalize_content(content)
        existing = await self.repository.find_exact(
            user_id=user_id,
            category=category,
            content=normalized,
        )
        if existing is not None:
            return existing
        return await self.repository.add(
            AgentMemory(
                user_id=user_id,
                category=category,
                content=normalized,
                source="agent_direct",
                confirmed_at=datetime.now(UTC),
            )
        )

    async def update(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        expected_version: int,
        category: MemoryCategory,
        content: str,
    ) -> AgentMemory:
        item = await self.repository.get_active(
            user_id=user_id,
            memory_id=memory_id,
            lock=True,
        )
        self._check_version(item, expected_version)
        if item is None:
            raise MemoryNotFoundError("Memory not found")
        item.category = category
        item.content = self._normalize_content(content)
        item.version += 1
        await self.repository.flush()
        return item

    async def delete(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        expected_version: int,
    ) -> AgentMemory:
        item = await self.repository.get_active(
            user_id=user_id,
            memory_id=memory_id,
            lock=True,
        )
        self._check_version(item, expected_version)
        if item is None:
            raise MemoryNotFoundError("Memory not found")
        item.deleted_at = datetime.now(UTC)
        item.version += 1
        await self.repository.flush()
        return item

    @staticmethod
    def _normalize_content(content: str) -> str:
        normalized = content.strip()
        if not normalized:
            raise ValueError("memory content must not be blank")
        if len(normalized) > 2000:
            raise ValueError("memory content must not exceed 2000 characters")
        return normalized

    @staticmethod
    def _check_version(item: AgentMemory | None, expected_version: int) -> None:
        if item is None:
            raise MemoryNotFoundError("Memory not found")
        if item.version != expected_version:
            raise MemoryConflictError("Memory was modified")
