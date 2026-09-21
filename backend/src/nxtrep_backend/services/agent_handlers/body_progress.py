from nxtrep_backend.schemas.agent import AgentBranchResult, AgentCitation
from nxtrep_backend.services.agent_context import build_contextual_user_payload
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_media import AgentImageAssetResolver, ResolvedAgentImage
from nxtrep_backend.services.body_image import BodyImageWorkflow
from nxtrep_backend.services.body_progress import BodyProgressPhotoService


class BodyProgressComparisonBranchHandler:
    """Compare two to four body images while preserving photo-quality limits."""

    def __init__(
        self,
        workflow: BodyImageWorkflow,
        progress_service: BodyProgressPhotoService,
        resolver: AgentImageAssetResolver,
    ) -> None:
        self._workflow = workflow
        self._progress_service = progress_service
        self._resolver = resolver

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        task = branch_input.task
        if task.task_type != "body_progress_comparison":
            raise ValueError(
                "BodyProgressComparisonBranchHandler requires a body_progress_comparison task"
            )
        missing_fields = list(dict.fromkeys(task.missing_fields))
        images = await self._complete_image_pair(branch_input)
        if len(images) < 2:
            if "comparison_body_images" not in missing_fields:
                missing_fields.append("comparison_body_images")
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                missing_fields=missing_fields,
            )

        assessment = await self._workflow.assess_resolved(
            question=build_contextual_user_payload(
                current_message=(
                    "请按照图片顺序把第一组视为较早状态、最后一组视为当前状态，"
                    "只比较在视角、光线和取景可比时能观察到的变化。"
                    f"用户要求：{branch_input.message}"
                ),
                conversation_context=branch_input.conversation_context,
                memories=branch_input.memories,
            ),
            images=images,
        )
        if not all(item.usable_for_assessment for item in assessment.photo_quality):
            if "comparable_body_images" not in missing_fields:
                missing_fields.append("comparable_body_images")

        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status="needs_input" if missing_fields else "completed",
            result={
                "comparison_order": [str(image.asset_id) for image in images],
                "assessment": assessment.model_dump(mode="json"),
            },
            missing_fields=missing_fields,
            citations=[
                AgentCitation(
                    source_type="image",
                    source_id=str(image.asset_id),
                    label="身体进度图片",
                )
                for image in images
            ],
        )

    async def _complete_image_pair(
        self,
        branch_input: AgentBranchInput,
    ) -> tuple[ResolvedAgentImage, ...]:
        current = list(branch_input.images)
        if len(current) >= 2:
            return tuple(current)
        existing_ids = {image.asset_id for image in current}
        saved = await self._progress_service.list(user_id=branch_input.user_id, limit=4)
        candidates = [
            item.image_asset_id for item in saved if item.image_asset_id not in existing_ids
        ]
        needed = 2 - len(current)
        selected_ids = candidates[:needed]
        if not selected_ids:
            return tuple(current)
        resolved = await self._resolver.resolve(
            user_id=branch_input.user_id,
            asset_ids=selected_ids,
        )
        if current:
            return (*resolved, *current)
        return tuple(reversed(resolved))
