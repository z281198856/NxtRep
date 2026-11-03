from uuid import UUID

from sqlalchemy import Select, String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import AgentConversation, AgentMessage, AgentRun, Confirmation


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
            statement = statement.with_for_update().execution_options(populate_existing=True)
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
                    func.coalesce(
                        AgentConversation.last_message_at, AgentConversation.created_at
                    ).desc(),
                    AgentConversation.id.desc(),
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

    async def list_conversation_confirmations(
        self, *, user_id: UUID, conversation_id: UUID
    ) -> list[Confirmation]:
        # Run results establish the conversation association; status and contents
        # always come from the command itself, never from an old AI response.
        payloads = await self.session.execute(
            select(AgentRun.result_payload["confirmation_cards"], AgentRun.checkpoint).where(
                AgentRun.user_id == user_id, AgentRun.conversation_id == conversation_id
            )
        )
        ids: set[UUID] = set()
        for cards, checkpoint in payloads:
            for card in cards if isinstance(cards, list) else []:
                if not isinstance(card, dict):
                    continue
                try:
                    ids.add(UUID(str(card.get("confirmation_id"))))
                except ValueError:
                    continue
            refs = (checkpoint or {}).get("confirmation_refs", [])
            for ref in refs if isinstance(refs, list) else []:
                try:
                    ids.add(UUID(str(ref)))
                except (ValueError, TypeError, AttributeError):
                    continue
        if not ids:
            return []
        chain = (
            select(Confirmation.id)
            .where(Confirmation.user_id == user_id, Confirmation.id.in_(ids))
            .cte("conversation_confirmation_chain", recursive=True)
        )
        # A portion editor can replace a card without creating a new Agent run.
        # UNION also terminates safely if legacy data contains a replacement cycle.
        chain = chain.union(
            select(Confirmation.id)
            .join(
                chain,
                Confirmation.after["replaces_confirmation_id"].astext == cast(chain.c.id, String),
            )
            .where(Confirmation.user_id == user_id)
        )
        return list(
            await self.session.scalars(
                select(Confirmation)
                .where(
                    Confirmation.user_id == user_id,
                    Confirmation.id.in_(select(chain.c.id)),
                )
                .order_by(Confirmation.created_at, Confirmation.id)
            )
        )

    async def confirmation_message_sequences(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> dict[str, int]:
        """Bind cards to the actual turn that first returned or journaled them."""
        messages = list(
            (
                await self.session.execute(
                    select(AgentMessage.sequence, AgentMessage.role, AgentMessage.created_at)
                    .join(AgentConversation)
                    .where(
                        AgentConversation.user_id == user_id,
                        AgentMessage.conversation_id == conversation_id,
                    )
                    .order_by(AgentMessage.sequence)
                )
            ).all()
        )
        users = [message for message in messages if message.role == "user"]
        roles = {message.sequence: message.role for message in messages}
        runs = await self.session.scalars(
            select(AgentRun)
            .where(
                AgentRun.user_id == user_id,
                AgentRun.conversation_id == conversation_id,
            )
            .order_by(AgentRun.started_at)
        )
        anchors: dict[str, int] = {}
        for run in runs:
            user = next(
                (message for message in reversed(users) if message.created_at <= run.started_at),
                None,
            )
            if user is None:
                continue
            sequence = (
                user.sequence + 1 if roles.get(user.sequence + 1) == "assistant" else user.sequence
            )
            cards = (run.result_payload or {}).get("confirmation_cards", [])
            refs = (run.checkpoint or {}).get("confirmation_refs", [])
            cards = cards if isinstance(cards, list) else []
            refs = refs if isinstance(refs, list) else []
            ids = [card.get("confirmation_id") for card in cards if isinstance(card, dict)]
            for identifier in [*ids, *refs]:
                if isinstance(identifier, str):
                    anchors.setdefault(identifier, sequence)
        return anchors
