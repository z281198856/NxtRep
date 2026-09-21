from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models.memory import AgentMemory


class SqlAlchemyMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, item: AgentMemory) -> AgentMemory:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_active(
        self,
        *,
        user_id: UUID,
        memory_id: UUID,
        lock: bool = False,
    ) -> AgentMemory | None:
        statement: Select[tuple[AgentMemory]] = select(AgentMemory).where(
            AgentMemory.id == memory_id,
            AgentMemory.user_id == user_id,
            AgentMemory.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def find_exact(
        self,
        *,
        user_id: UUID,
        category: str,
        content: str,
    ) -> AgentMemory | None:
        return await self.session.scalar(
            select(AgentMemory).where(
                AgentMemory.user_id == user_id,
                AgentMemory.category == category,
                AgentMemory.content == content,
                AgentMemory.deleted_at.is_(None),
            )
        )

    async def flush(self) -> None:
        await self.session.flush()

    async def list_active(
        self,
        *,
        user_id: UUID,
        category: str | None,
        limit: int,
    ) -> list[AgentMemory]:
        conditions = [
            AgentMemory.user_id == user_id,
            AgentMemory.deleted_at.is_(None),
        ]
        if category is not None:
            conditions.append(AgentMemory.category == category)
        return list(
            await self.session.scalars(
                select(AgentMemory)
                .where(*conditions)
                .order_by(AgentMemory.confirmed_at.desc(), AgentMemory.id)
                .limit(limit)
            )
        )
