from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.schemas.agent import (
    AgentBranchError,
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
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_resolution import observation_input_fields
from nxtrep_backend.services.agent_task_parameters import remaining_draft_fields
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.nutrition_image import NutritionImageAnalysisService


class NutritionRecordDraftBranchHandler:
    """Turn a food-photo analysis into one reviewable nutrition-entry proposal."""

    def __init__(
        self,
        analysis_service: NutritionImageAnalysisService,
        nutrition_service: NutritionService,
        text_handler: GeneralQuestionBranchHandler | None = None,
    ) -> None:
        self._analysis_service = analysis_service
        self._nutrition_service = nutrition_service
        self._text_handler = text_handler

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        task = branch_input.task
        if task.task_type != "nutrition_record_draft":
            raise ValueError(
                "NutritionRecordDraftBranchHandler requires a nutrition_record_draft task"
            )

        entities = task.task_update.entities if task.task_update else {}
        bound_meal = any(entities.get(key) for key in ("confirmation_id", "entry_id", "meal_id"))
        if (not branch_input.images or bound_meal) and self._text_handler is not None:
            text_task = task.model_copy(
                update={
                    "task_type": "nutrition_entry_update_draft"
                    if entities.get("entry_id") or entities.get("meal_id")
                    else task.task_type,
                    "missing_fields": [
                        field
                        for field in task.missing_fields
                        if field not in {"food_images", "meal_type", "eaten_at", "food_selection"}
                    ],
                }
            )
            return await self._text_handler.execute(replace(branch_input, task=text_task))

        if bound_meal:
            # A new photo can be evidence for an existing meal. It is never
            # authorization to bypass the scoped revision tools and create a second meal.
            return AgentBranchResult(
                task_type=task.task_type,
                status="needs_input",
                missing_fields=["nutrition_correction"],
                result={
                    "task_answer": "当前餐食需要走原记录的修订流程，尚未创建新餐。"
                    "请返回原餐食草稿继续修改。"
                },
            )

        missing_fields = list(dict.fromkeys(task.missing_fields))
        meal_type, eaten_at, metadata_notes = self._meal_metadata(branch_input)
        if meal_type is not None and "meal_type" in missing_fields:
            missing_fields.remove("meal_type")
        if eaten_at is not None and "eaten_at" in missing_fields:
            missing_fields.remove("eaten_at")
        if meal_type is None and "meal_type" not in missing_fields:
            missing_fields.append("meal_type")
        if eaten_at is None and "eaten_at" not in missing_fields:
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
        missing_fields = [field for field in missing_fields if field != "food_images"]

        failed_prior = next(
            (
                result
                for result in branch_input.prior_results
                if result.task_type == "nutrition_analysis"
                and result.status == "failed"
                and set(result.asset_ids) == set(task.asset_ids)
            ),
            None,
        )
        if failed_prior is not None:
            return AgentBranchResult(
                task_type=task.task_type,
                asset_ids=task.asset_ids,
                status="failed",
                error=failed_prior.error
                or AgentBranchError(
                    code="FOOD_ANALYSIS_FAILED",
                    message="本次食物照片分析未完成，请稍后重试。",
                    retryable=True,
                ),
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
        if analysis.calculation.is_complete:
            parameters = task.task_update.parameters if task.task_update else {}
            missing_fields = remaining_draft_fields(
                task.task_type,
                [field for field in missing_fields if field != "food_selection"],
                {
                    **parameters,
                    "items": [
                        {"food_name": food.name, "amount_g": str(food.estimated_amount_g)}
                        for food in analysis.recognition.foods
                    ],
                },
                entities,
                invalid_fields=task.task_update.invalid_fields if task.task_update else [],
            )
        missing_fields = observation_input_fields(task, missing_fields)
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
            meal_type=meal_type,
            eaten_at=eaten_at,
            items=self._entry_items(analysis),
            notes="\n".join(
                [
                    branch_input.message,
                    *metadata_notes,
                    "照片食物和份量为估测，请核对；重量、用油和酱料可能存在误差。",
                    *analysis.recognition.assumptions,
                ]
            )[:2000],
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
    def _meal_metadata(branch_input):
        """Semantic meal date/type outrank the client's upload timestamp."""
        parameters = (
            branch_input.task.task_update.parameters if branch_input.task.task_update else {}
        )
        hints = branch_input.context_hints
        meal = parameters.get("meal_type", hints.meal_type)
        if meal not in {"breakfast", "lunch", "dinner", "snack", "other"}:
            meal = None
        try:
            zone = ZoneInfo(hints.timezone or parameters.get("timezone") or "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("Asia/Shanghai")
        try:
            day = date.fromisoformat(str(parameters["date"])) if parameters.get("date") else None
            if parameters.get("eaten_at"):
                value = datetime.fromisoformat(str(parameters["eaten_at"]))
                if value.tzinfo is None or (day and value.astimezone(zone).date() != day):
                    return meal, None, []
                return meal, value, []
            if day is not None:
                hours = {"breakfast": 8, "lunch": 12, "dinner": 19, "snack": 15, "other": 12}
                clock = (
                    time.fromisoformat(str(parameters["eaten_time"]))
                    if parameters.get("eaten_time")
                    else time(hours.get(meal, 12))
                )
                notes = (
                    []
                    if parameters.get("eaten_time")
                    else [f"具体进餐时间未提供，暂按{clock.strftime('%H:%M')}记录，可修改。"]
                )
                return meal, datetime.combine(day, clock, zone), notes
        except (ValueError, TypeError):
            return meal, None, []
        return meal, hints.occurred_at, []

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
                    estimate_assumptions="；".join(
                        [
                            *analysis.recognition.assumptions,
                            *item.assumptions,
                            "照片份量估测，实际食材、用油和酱料可能不同",
                        ]
                    )[:2000],
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
