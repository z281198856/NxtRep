import json
from dataclasses import replace
from uuid import UUID

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.agent import AgentBranchError, AgentBranchResult
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError


class TrainingPlanWorkflowError(RuntimeError):
    pass


class TrainingPlanBranchHandler:
    """Enforce that a training-plan task ends in a validated confirmation draft."""

    def __init__(
        self,
        react_handler: GeneralQuestionBranchHandler,
        tool_context: AgentToolContext | None = None,
    ) -> None:
        self._react_handler = react_handler
        self._tool_context = tool_context

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        if branch_input.task.task_type != "training_plan_draft":
            raise ValueError("TrainingPlanBranchHandler requires a training_plan_draft task")
        personal_context = await self._personal_context(branch_input)
        enriched_input = branch_input
        if personal_context:
            enriched_input = replace(
                branch_input,
                message=json.dumps(
                    {
                        "current_user_message": branch_input.message,
                        "verified_user_context": personal_context,
                        "context_note": (
                            "以下是数据库已记录的资料。缺失字段不能推测；"
                            "身高、体重和体脂只用于解释与跟踪，不能单独决定训练强度。"
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
        result = await self._react_handler.execute(enriched_input)
        if result.status != "completed":
            return result
        if not any(
            card.operation_type == "training_plan_activate" for card in result.confirmation_cards
        ):
            return AgentBranchResult(
                task_type=branch_input.task.task_type,
                asset_ids=branch_input.task.asset_ids,
                status="failed",
                error=AgentBranchError(
                    code="TRAINING_PLAN_DRAFT_NOT_CREATED",
                    message="AI 未能创建可确认的训练计划草稿，请稍后重试。",
                    retryable=True,
                ),
            )
        operations = await self._enrich_draft_preview(branch_input, result.operation_results)
        updates: dict = {"operation_results": operations}
        if personal_context:
            updates["result"] = {
                **(result.result or {}),
                "personal_context": personal_context,
            }
        return result.model_copy(update=updates)

    async def _enrich_draft_preview(
        self, branch_input: AgentBranchInput, operations: list[dict]
    ) -> list[dict]:
        tools = self._tool_context
        if tools is None:
            return operations
        exercise_ids: set[UUID] = set()
        for operation in operations:
            draft = operation.get("draft")
            if not isinstance(draft, dict):
                continue
            for day in draft.get("days", []):
                if not isinstance(day, dict):
                    continue
                for exercise in day.get("exercises", []):
                    if isinstance(exercise, dict) and exercise.get("exercise_id"):
                        try:
                            exercise_ids.add(UUID(str(exercise["exercise_id"])))
                        except ValueError:
                            continue
        if not exercise_ids:
            return operations
        names = await tools.training_service.repository.plan_exercise_names(
            branch_input.user_id, exercise_ids
        )
        enriched = []
        for operation in operations:
            draft = operation.get("draft")
            if not isinstance(draft, dict):
                enriched.append(operation)
                continue
            days = []
            for day in draft.get("days", []):
                if not isinstance(day, dict):
                    continue
                days.append(
                    {
                        **day,
                        "exercises": [
                            {
                                **exercise,
                                "exercise_name": names.get(
                                    str(exercise.get("exercise_id")), "动作已不可用"
                                ),
                            }
                            for exercise in day.get("exercises", [])
                            if isinstance(exercise, dict)
                        ],
                    }
                )
            enriched.append({**operation, "draft": {**draft, "days": days}})
        return enriched

    async def _personal_context(self, branch_input: AgentBranchInput) -> dict:
        tools = self._tool_context
        if tools is None:
            return {}
        context: dict = {}
        try:
            profile = await tools.profile_service.get_profile(user_id=branch_input.user_id)
        except ProfileNotFoundError:
            pass
        else:
            context["profile"] = {
                "height_cm": (
                    format(profile.height_cm.normalize(), "f")
                    if profile.height_cm is not None
                    else None
                ),
                "experience_level": profile.experience_level,
                "weekly_training_days": profile.weekly_training_days,
                "session_duration_minutes": profile.session_duration_minutes,
            }
        try:
            goals = await tools.goals_service.get_goals_and_constraints(
                user_id=branch_input.user_id
            )
        except GoalsNotFoundError:
            pass
        else:
            context["goal_type"] = goals.goal.goal_type
        context["measurements"] = await tools.body_service.recent_measurement_summary(
            branch_input.user_id
        )
        return context
