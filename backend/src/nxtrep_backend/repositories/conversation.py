from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import AgentConversation, AgentMessage


class SqlAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_conversation(
        self,
        conversation: AgentConversation,
    ) -> AgentConversation:
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_for_user(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        lock: bool = False,
        active_only: bool = True,
    ) -> AgentConversation | None:
        conditions = [
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
            AgentConversation.deleted_at.is_(None),
        ]
        if active_only:
            conditions.append(AgentConversation.status == "active")
        statement: Select[tuple[AgentConversation]] = select(AgentConversation).where(*conditions)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AgentConversation], int]:
        conditions = [
            AgentConversation.user_id == user_id,
            AgentConversation.deleted_at.is_(None),
        ]
        if status is not None:
            conditions.append(AgentConversation.status == status)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AgentConversation).where(*conditions)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(AgentConversation)
                .where(*conditions)
                .order_by(
                    AgentConversation.last_message_at.desc().nullslast(),
                    AgentConversation.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return rows, total

    async def list_messages(
        self,
        *,
        conversation_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> list[AgentMessage]:
        return list(
            await self.session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sequence > after_sequence,
                )
                .order_by(AgentMessage.sequence)
                .limit(limit)
            )
        )

    async def append_message(
        self,
        *,
        conversation: AgentConversation,
        role: str,
        content: str,
        image_asset_ids: list[str] | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            conversation_id=conversation.id,
            role=role,
            content=content,
            sequence=conversation.next_sequence,
            image_asset_ids=image_asset_ids or [],
        )
        conversation.next_sequence += 1
        conversation.last_message_at = message.created_at
        conversation.version += 1
        self.session.add(message)
        await self.session.flush()
        conversation.last_message_at = message.created_at
        return message

    async def list_recent(
        self,
        *,
        conversation_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> list[AgentMessage]:
        rows = list(
            await self.session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sequence > after_sequence,
                )
                .order_by(AgentMessage.sequence.desc())
                .limit(limit)
            )
        )
        rows.reverse()
        return rows

    async def list_unsummarized(
        self,
        *,
        conversation_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> list[AgentMessage]:
        return list(
            await self.session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.conversation_id == conversation_id,
                    AgentMessage.sequence > after_sequence,
                )
                .order_by(AgentMessage.sequence)
                .limit(limit)
            )
        )

    async def flush(self) -> None:
        await self.session.flush()
