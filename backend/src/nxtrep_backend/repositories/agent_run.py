from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import AgentConversation, AgentRun, Confirmation


class SqlAlchemyAgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, item: AgentRun) -> AgentRun:
        self.session.add(item)
        await self.session.flush()
        return item

    async def lock_conversation(self, user_id: UUID, conversation_id: UUID) -> bool:
        # A short transaction lock makes claiming an empty conversation safe as
        # well as claiming one which already has runs. Never hold it for an LLM.
        return await self.session.scalar(
            select(AgentConversation.id).where(
                AgentConversation.id == conversation_id,
                AgentConversation.user_id == user_id,
                AgentConversation.deleted_at.is_(None),
            ).with_for_update()
        ) is not None

    async def list_active(self, user_id: UUID, conversation_id: UUID) -> list[AgentRun]:
        return list(await self.session.scalars(
            select(AgentRun).where(
                AgentRun.user_id == user_id,
                AgentRun.conversation_id == conversation_id,
                AgentRun.status.in_(["running", "cancel_requested"]),
            ).with_for_update().execution_options(populate_existing=True)
        ))

    async def existing_confirmation_refs(self, user_id: UUID, refs: list[UUID]) -> set[UUID]:
        if not refs:
            return set()
        return set(await self.session.scalars(
            select(Confirmation.id).where(
                Confirmation.user_id == user_id, Confirmation.id.in_(refs),
            )
        ))

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
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def get_owned_by_client_turn(
        self, *, user_id: UUID, client_turn_id: UUID,
    ) -> AgentRun | None:
        """Find the durable action even after the short response cache expires."""
        return await self.session.scalar(
            select(AgentRun).where(
                AgentRun.user_id == user_id,
                or_(
                    AgentRun.checkpoint["client_turn_id"].astext == str(client_turn_id),
                    AgentRun.request_payload["client_turn_id"].astext == str(client_turn_id),
                ),
            ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1)
            .execution_options(populate_existing=True)
        )

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

    async def refresh_locked(self, item: AgentRun) -> None:
        # Only transition paths call this and commit/rollback immediately. Pure
        # cancellation polling must not hold this lock while waiting for an LLM.
        await self.session.refresh(item, with_for_update=True)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
