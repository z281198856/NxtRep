from dataclasses import dataclass, field
from uuid import UUID

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentContextHints,
    AgentIntentPlan,
)
from nxtrep_backend.services.agent_context import (
    ActiveMemoryContext,
    AgentContextAssembler,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.conversation import AgentConversationContext


@dataclass(frozen=True, slots=True)
class PlannedAgentRequest:
    images: tuple[ResolvedAgentImage, ...]
    intent_plan: AgentIntentPlan
    conversation_context: AgentConversationContext = AgentConversationContext()
    memories: tuple[ActiveMemoryContext, ...] = ()
    context_hints: AgentContextHints = field(default_factory=AgentContextHints)


class AgentRequestPlanner:
    def __init__(
        self,
        *,
        resolver: AgentImageAssetResolver,
        intent_router: AgentIntentRouter,
        context_assembler: AgentContextAssembler,
    ) -> None:
        self._resolver = resolver
        self._intent_router = intent_router
        self._context_assembler = context_assembler

    async def plan(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
        conversation_context: AgentConversationContext,
    ) -> PlannedAgentRequest:
        if request.image_asset_ids:
            images = await self._resolver.resolve(
                user_id=user_id,
                asset_ids=request.image_asset_ids,
            )
        else:
            images = []

        intent_plan = await self._intent_router.route(
            message=request.message,
            images=images,
            conversation_context=conversation_context,
            context_hints=request.context_hints,
        )
        memories = await self._context_assembler.load_memories(
            user_id=user_id,
            intent_plan=intent_plan,
        )

        return PlannedAgentRequest(
            images=tuple(images),
            intent_plan=intent_plan,
            conversation_context=conversation_context,
            memories=memories,
            context_hints=request.context_hints,
        )
