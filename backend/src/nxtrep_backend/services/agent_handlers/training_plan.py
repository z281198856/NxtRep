from nxtrep_backend.schemas.agent import AgentBranchResult
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler


class TrainingPlanWorkflowError(RuntimeError):
    pass


class TrainingPlanBranchHandler:
    """Enforce that a training-plan task ends in a validated confirmation draft."""

    def __init__(self, react_handler: GeneralQuestionBranchHandler) -> None:
        self._react_handler = react_handler

    async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
        if branch_input.task.task_type != "training_plan_draft":
            raise ValueError("TrainingPlanBranchHandler requires a training_plan_draft task")
        result = await self._react_handler.execute(branch_input)
        if result.status != "completed":
            return result
        if not any(
            card.operation_type == "training_plan_activate" for card in result.confirmation_cards
        ):
            raise TrainingPlanWorkflowError(
                "Training plan generation did not create a validated confirmation draft"
            )
        return result
