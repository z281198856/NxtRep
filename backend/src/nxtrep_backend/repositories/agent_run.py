from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import AgentRun


class SqlAlchemyAgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, item: AgentRun) -> AgentRun:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_owned(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        lock: bool = False,
    ) -> AgentRun | None:
        statement = select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def flush(self) -> None:
        await self.session.flush()

    async def list_owned(
        self, user_id: UUID, page: int, page_size: int
    ) -> tuple[list[AgentRun], int]:
        condition = AgentRun.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(AgentRun).where(condition)
        )
        items = list(
            await self.session.scalars(
                select(AgentRun)
                .where(condition)
                .order_by(AgentRun.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def refresh(self, item: AgentRun) -> None:
        await self.session.refresh(item)

    async def commit(self) -> None:
        await self.session.commit()
