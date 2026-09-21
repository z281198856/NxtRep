from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentExecutionBundle,
)


class AgentExecutionSafetyValidator:
    """Enforce deterministic write-safety rules after model/tool execution."""

    _confirmation_required_tasks = {
        "training_plan_draft",
        "nutrition_record_draft",
        "body_measurement_draft",
    }

    def validate(self, bundle: AgentExecutionBundle) -> AgentExecutionBundle:
        return bundle.model_copy(
            update={
                "branch_results": [
                    self._validate_branch(branch) for branch in bundle.branch_results
                ]
            }
        )

    def _validate_branch(self, branch: AgentBranchResult) -> AgentBranchResult:
        confirmation_operations = [
            item
            for item in branch.operation_results
            if item.get("status") == "confirmation_required"
        ]
        must_confirm = (
            branch.task_type in self._confirmation_required_tasks and branch.status == "completed"
        ) or bool(confirmation_operations)

        if must_confirm and not branch.confirmation_cards:
            return AgentBranchResult(
                task_type=branch.task_type,
                asset_ids=branch.asset_ids,
                status="failed",
                error=AgentBranchError(
                    code="UNSAFE_WRITE_RESULT",
                    message="A formal write result did not include a confirmation card",
                    retryable=False,
                ),
            )

        if branch.requires_confirmation and not branch.confirmation_cards:
            return AgentBranchResult(
                task_type=branch.task_type,
                asset_ids=branch.asset_ids,
                status="failed",
                error=AgentBranchError(
                    code="MISSING_CONFIRMATION_CARD",
                    message="The branch requires confirmation but returned no confirmation card",
                    retryable=False,
                ),
            )

        if branch.confirmation_cards and not branch.requires_confirmation:
            return branch.model_copy(update={"requires_confirmation": True})

        return branch
