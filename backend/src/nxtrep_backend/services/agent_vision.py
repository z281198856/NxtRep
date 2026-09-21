from collections.abc import Sequence
from uuid import UUID

from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
)


class AgentVisionContextService:
    def __init__(
        self,
        resolver: AgentImageAssetResolver,
        analyzer: GlmVisionAnalyzer,
    ) -> None:
        self._resolver = resolver
        self._analyzer = analyzer

    async def build_context(
        self,
        *,
        user_id: UUID,
        question: str,
        asset_ids: Sequence[UUID],
    ) -> str | None:
        if not asset_ids:
            return None

        images = await self._resolver.resolve(
            user_id=user_id,
            asset_ids=asset_ids,
        )

        return await self._analyzer.analyze(
            question=question,
            images=images,
        )
