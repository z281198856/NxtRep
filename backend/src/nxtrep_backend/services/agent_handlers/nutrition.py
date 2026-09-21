from nxtrep_backend.schemas.agent import AgentBranchResult
from nxtrep_backend.services.agent_context import build_contextual_user_payload
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.nutrition_image import (
    NutritionImageAnalysisService,
)


class NutritionAnalysisBranchHandler:
    def __init__(
        self,
        analysis_service: NutritionImageAnalysisService,
    ) -> None:
        self._analysis_service = analysis_service

    async def execute(
        self,
        branch_input: AgentBranchInput,
    ) -> AgentBranchResult:
        task = branch_input.task

        if task.task_type != "nutrition_analysis":
            raise ValueError("NutritionAnalysisBranchHandler requires a nutrition_analysis task")

        missing_fields = list(dict.fromkeys(task.missing_fields))

        if not branch_input.images:
            if "food_images" not in missing_fields:
                missing_fields.append("food_images")

            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                missing_fields=missing_fields,
            )

        analysis = await self._analysis_service.analyze(
            user_id=branch_input.user_id,
            images=branch_input.images,
            notes=build_contextual_user_payload(
                current_message=branch_input.message,
                conversation_context=branch_input.conversation_context,
                memories=branch_input.memories,
            ),
        )

        if not analysis.recognition.foods:
            if "identifiable_food" not in missing_fields:
                missing_fields.append("identifiable_food")

        status = "needs_input" if missing_fields else "completed"

        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status=status,
            result=analysis.model_dump(mode="json"),
            missing_fields=missing_fields,
            requires_confirmation=(analysis.calculation.requires_confirmation),
        )
