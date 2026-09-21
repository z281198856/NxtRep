from uuid import uuid4

from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentConfirmationCard,
    AgentExecutionBundle,
)
from nxtrep_backend.services.agent_safety import AgentExecutionSafetyValidator


def test_formal_write_without_confirmation_card_is_rejected() -> None:
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="training_plan_draft",
                status="completed",
                result={"answer": "plan"},
            )
        ]
    )

    result = AgentExecutionSafetyValidator().validate(bundle)

    branch = result.branch_results[0]
    assert branch.status == "failed"
    assert branch.error is not None
    assert branch.error.code == "UNSAFE_WRITE_RESULT"


def test_confirmation_card_sets_requires_confirmation() -> None:
    card = AgentConfirmationCard(
        confirmation_id=uuid4(),
        operation_type="nutrition_entry_create",
        status="pending",
        impact="保存饮食记录",
        expires_at="2026-09-09T00:00:00+08:00",
        version=1,
    )
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="nutrition_record_draft",
                status="completed",
                result={"draft": {}},
                confirmation_cards=[card],
            )
        ]
    )

    result = AgentExecutionSafetyValidator().validate(bundle)

    assert result.branch_results[0].requires_confirmation is True
