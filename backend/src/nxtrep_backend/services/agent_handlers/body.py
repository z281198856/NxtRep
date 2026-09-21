from nxtrep_backend.schemas.agent import AgentBranchResult
from nxtrep_backend.services.agent_context import build_contextual_user_payload
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.body_image import BodyImageWorkflow


class BodyAssessmentBranchHandler:
    def __init__(
        self,
        workflow: BodyImageWorkflow,
    ) -> None:
        self._workflow = workflow

    async def execute(
        self,
        branch_input: AgentBranchInput,
    ) -> AgentBranchResult:
        task = branch_input.task

        if task.task_type != "body_assessment":
            raise ValueError("BodyAssessmentBranchHandler requires a body_assessment task")

        missing_fields = list(dict.fromkeys(task.missing_fields))

        if not branch_input.images:
            if "body_images" not in missing_fields:
                missing_fields.append("body_images")

            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                missing_fields=missing_fields,
            )

        assessment = await self._workflow.assess_resolved(
            question=build_contextual_user_payload(
                current_message=branch_input.message,
                conversation_context=branch_input.conversation_context,
                memories=branch_input.memories,
            ),
            images=branch_input.images,
        )

        if not any(quality.usable_for_assessment for quality in assessment.photo_quality):
            if "usable_body_image" not in missing_fields:
                missing_fields.append("usable_body_image")

        status = "needs_input" if missing_fields else "completed"

        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status=status,
            result=assessment.model_dump(mode="json"),
            missing_fields=missing_fields,
            requires_confirmation=False,
        )
