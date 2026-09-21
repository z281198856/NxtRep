from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentExecutionBundle,
)


def make_error() -> AgentBranchError:
    return AgentBranchError(
        code="VISION_TIMEOUT",
        message="身体图片分析暂时超时。",
        retryable=True,
    )


def test_completed_branch_requires_result_without_error() -> None:
    result = AgentBranchResult(
        task_type="body_assessment",
        status="completed",
        result={"summary": "肩部可能存在轻微不平衡。"},
    )

    assert result.status == "completed"
    assert result.error is None

    with pytest.raises(ValidationError, match="requires result"):
        AgentBranchResult(
            task_type="body_assessment",
            status="completed",
        )

    with pytest.raises(ValidationError, match="cannot contain error"):
        AgentBranchResult(
            task_type="body_assessment",
            status="completed",
            result={"summary": "有效结果"},
            error=make_error(),
        )


def test_needs_input_branch_requires_missing_fields_without_error() -> None:
    result = AgentBranchResult(
        task_type="nutrition_analysis",
        status="needs_input",
        result={"estimated_kcal": 520},
        missing_fields=["cooking_oil_amount"],
        requires_confirmation=True,
    )

    assert result.missing_fields == ["cooking_oil_amount"]
    assert result.requires_confirmation is True

    with pytest.raises(ValidationError, match="requires missing_fields"):
        AgentBranchResult(
            task_type="nutrition_analysis",
            status="needs_input",
        )

    with pytest.raises(ValidationError, match="cannot contain error"):
        AgentBranchResult(
            task_type="nutrition_analysis",
            status="needs_input",
            missing_fields=["meal_type"],
            error=make_error(),
        )


def test_failed_branch_requires_error_without_result() -> None:
    result = AgentBranchResult(
        task_type="body_assessment",
        status="failed",
        error=make_error(),
    )

    assert result.error is not None
    assert result.error.retryable is True

    with pytest.raises(ValidationError, match="requires error"):
        AgentBranchResult(
            task_type="body_assessment",
            status="failed",
        )

    with pytest.raises(ValidationError, match="cannot contain result"):
        AgentBranchResult(
            task_type="body_assessment",
            status="failed",
            result={"summary": "不应保留的结果"},
            error=make_error(),
        )


def test_execution_bundle_supports_partial_success() -> None:
    body_asset_id = uuid4()
    meal_asset_id = uuid4()
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="body_assessment",
                asset_ids=[body_asset_id],
                status="completed",
                result={"summary": "身体评估已完成。"},
            ),
            AgentBranchResult(
                task_type="nutrition_analysis",
                asset_ids=[meal_asset_id],
                status="needs_input",
                result={"estimated_kcal": 520},
                missing_fields=["cooking_oil_amount"],
            ),
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="failed",
                error=AgentBranchError(
                    code="RAG_UNAVAILABLE",
                    message="知识检索暂时不可用。",
                    retryable=True,
                ),
            ),
        ],
        clarification_questions=["这顿饭大约用了多少油？"],
    )

    assert [item.status for item in bundle.branch_results] == [
        "completed",
        "needs_input",
        "failed",
    ]


def test_branch_result_rejects_duplicate_asset_ids() -> None:
    asset_id = uuid4()

    with pytest.raises(ValidationError, match="asset_ids must be unique"):
        AgentBranchResult(
            task_type="body_assessment",
            asset_ids=[asset_id, asset_id],
            status="completed",
            result={"summary": "有效结果"},
        )


def test_execution_bundle_rejects_duplicate_unassigned_asset_ids() -> None:
    asset_id = uuid4()

    with pytest.raises(
        ValidationError,
        match="unassigned_asset_ids must be unique",
    ):
        AgentExecutionBundle(
            branch_results=[
                AgentBranchResult(
                    task_type="general_question",
                    status="completed",
                    result={"message": "回答"},
                )
            ],
            unassigned_asset_ids=[asset_id, asset_id],
        )


def test_execution_bundle_rejects_assigned_and_unassigned_asset() -> None:
    asset_id = uuid4()

    with pytest.raises(ValidationError, match="assigned and unassigned"):
        AgentExecutionBundle(
            branch_results=[
                AgentBranchResult(
                    task_type="body_assessment",
                    asset_ids=[asset_id],
                    status="completed",
                    result={"summary": "身体评估已完成。"},
                )
            ],
            unassigned_asset_ids=[asset_id],
        )
