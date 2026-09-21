from collections.abc import Sequence
from uuid import UUID

from nxtrep_backend.agents.body_vision import GlmBodyImageAssessor
from nxtrep_backend.schemas.body import BodyImageAssessmentResult
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)


class BodyImagePurposeError(RuntimeError):
    pass


class BodyImageWorkflow:
    def __init__(
        self,
        *,
        resolver: AgentImageAssetResolver,
        assessor: GlmBodyImageAssessor,
    ) -> None:
        self._resolver = resolver
        self._assessor = assessor

    async def assess(
        self,
        *,
        user_id: UUID,
        question: str,
        asset_ids: Sequence[UUID],
    ) -> BodyImageAssessmentResult:
        if not asset_ids:
            raise ValueError("At least one body image is required")

        images = await self._resolver.resolve(
            user_id=user_id,
            asset_ids=asset_ids,
        )

        return await self.assess_resolved(
            question=question,
            images=images,
        )

    async def assess_resolved(
        self,
        *,
        question: str,
        images: Sequence[ResolvedAgentImage],
    ) -> BodyImageAssessmentResult:
        if not images:
            raise ValueError("At least one resolved body image is required")

        allowed_purposes = {
            ImagePurpose.BODY_PROGRESS,
            ImagePurpose.CHAT_ATTACHMENT,
        }

        if any(image.purpose not in allowed_purposes for image in images):
            raise BodyImagePurposeError("Images must be body progress or chat attachments")

        return await self._assessor.assess(
            images=images,
            question=question,
        )
