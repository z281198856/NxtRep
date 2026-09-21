from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentCitation,
    AgentConfirmationCard,
)
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionImageAnalysisResult,
    NutritionItemInput,
)
from nxtrep_backend.services.agent_context import build_contextual_user_payload
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.nutrition_image import NutritionImageAnalysisService


class NutritionRecordDraftBranchHandler:
    """Turn a food-photo analysis into one reviewable nutrition-entry proposal."""

    def __init__(
        self,
        analysis_service: NutritionImageAnalysisService,
        nutrition_service: NutritionService,
    ) -> None:
        self._analysis_service = analysis_service
        self._nutrition_service = nutrition_service

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        task = branch_input.task
        if task.task_type != "nutrition_record_draft":
            raise ValueError(
                "NutritionRecordDraftBranchHandler requires a nutrition_record_draft task"
            )

        missing_fields = list(dict.fromkeys(task.missing_fields))
        hints = branch_input.context_hints
        if hints.meal_type is not None and "meal_type" in missing_fields:
            missing_fields.remove("meal_type")
        if hints.occurred_at is not None and "eaten_at" in missing_fields:
            missing_fields.remove("eaten_at")
        if hints.meal_type is None and "meal_type" not in missing_fields:
            missing_fields.append("meal_type")
        if hints.occurred_at is None and "eaten_at" not in missing_fields:
            missing_fields.append("eaten_at")
        if not branch_input.images:
            if "food_images" not in missing_fields:
                missing_fields.append("food_images")
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                missing_fields=missing_fields,
            )

        analysis = self._prior_analysis(branch_input)
        if analysis is None:
            analysis = await self._analysis_service.analyze(
                user_id=branch_input.user_id,
                images=branch_input.images,
                notes=build_contextual_user_payload(
                    current_message=branch_input.message,
                    conversation_context=branch_input.conversation_context,
                    memories=branch_input.memories,
                ),
            )

        result_payload = {"analysis": analysis.model_dump(mode="json")}
        if not analysis.recognition.foods:
            if "identifiable_food" not in missing_fields:
                missing_fields.append("identifiable_food")
        if not analysis.calculation.is_complete:
            if "food_selection" not in missing_fields:
                missing_fields.append("food_selection")
        if missing_fields:
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="needs_input",
                result=result_payload,
                missing_fields=missing_fields,
                citations=self._image_citations(branch_input),
            )

        entry = NutritionEntryCreateRequest(
            meal_type=hints.meal_type,
            eaten_at=hints.occurred_at,
            items=self._entry_items(analysis),
            notes=branch_input.message,
        )
        confirmation = await self._nutrition_service.propose_entry(
            user_id=branch_input.user_id,
            body=entry,
        )
        operation = {
            "status": "confirmation_required",
            "draft": entry.model_dump(mode="json"),
            "confirmation": confirmation_payload(confirmation),
        }
        card = AgentConfirmationCard.model_validate(operation["confirmation"])
        result_payload["draft"] = json_safe(entry)
        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status="completed",
            result=result_payload,
            operation_results=[operation],
            confirmation_cards=[card],
            citations=self._image_citations(branch_input),
            requires_confirmation=True,
        )

    @staticmethod
    def _prior_analysis(branch_input: AgentBranchInput) -> NutritionImageAnalysisResult | None:
        expected_ids = set(branch_input.task.asset_ids)
        for result in branch_input.prior_results:
            if (
                result.task_type == "nutrition_analysis"
                and result.status in {"completed", "needs_input"}
                and set(result.asset_ids) == expected_ids
                and result.result is not None
            ):
                return NutritionImageAnalysisResult.model_validate(result.result)
        return None

    @staticmethod
    def _entry_items(analysis: NutritionImageAnalysisResult) -> list[NutritionItemInput]:
        items: list[NutritionItemInput] = []
        for item in analysis.calculation.items:
            detected = item.match.detected
            if item.match.selected is not None:
                items.append(
                    NutritionItemInput(
                        food_version_id=item.match.selected.food_version_id,
                        amount_g=detected.estimated_amount_g,
                    )
                )
                continue
            if item.nutrition is None:
                raise ValueError("Complete nutrition analysis contains an unresolved food")
            estimated = item.nutrition.estimated
            items.append(
                NutritionItemInput(
                    amount_g=detected.estimated_amount_g,
                    name=detected.name,
                    basis_amount_g=detected.estimated_amount_g,
                    kcal=estimated.kcal,
                    protein_g=estimated.protein_g,
                    carbs_g=estimated.carbs_g,
                    fat_g=estimated.fat_g,
                    source=item.source or "model_estimated",
                    confidence=item.confidence or "low",
                )
            )
        return items

    @staticmethod
    def _image_citations(branch_input: AgentBranchInput) -> list[AgentCitation]:
        return [
            AgentCitation(
                source_type="image",
                source_id=str(image.asset_id),
                label="食物图片",
            )
            for image in branch_input.images
        ]
