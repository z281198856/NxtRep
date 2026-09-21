from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from nxtrep_backend.evaluation.agent import (
    AgentEvaluationCase,
    build_agent_evaluation_report,
    evaluate_agent_response,
    load_agent_asset_fixtures,
    load_agent_evaluation_cases,
    resolve_agent_evaluation_request,
)
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentChatResponse,
    AgentCitation,
    AgentConfirmationCard,
)


def confirmation_card() -> AgentConfirmationCard:
    return AgentConfirmationCard(
        confirmation_id=uuid4(),
        operation_type="training_plan.activate",
        status="pending",
        impact="Activates a training plan after confirmation",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        version=1,
    )


def test_packaged_non_rag_evaluation_dataset_is_valid() -> None:
    dataset = (
        Path(__file__).parents[1]
        / "src"
        / "nxtrep_backend"
        / "evaluation"
        / "datasets"
        / "non_rag_agent.json"
    )

    cases = load_agent_evaluation_cases(dataset)

    assert len(cases) == 6
    assert all("knowledge_retrieval" not in case.expected_task_types for case in cases)


def test_packaged_rag_evaluation_dataset_is_valid() -> None:
    dataset = (
        Path(__file__).parents[1]
        / "src"
        / "nxtrep_backend"
        / "evaluation"
        / "datasets"
        / "rag_agent.template.json"
    )

    cases = load_agent_evaluation_cases(dataset)

    assert len(cases) == 4
    assert all(case.expected_task_types == ["knowledge_retrieval"] for case in cases)
    by_id = {case.case_id: case for case in cases}
    assert by_id["adult_activity_guideline_grounded"].required_knowledge_source_ids == [
        "hhs-2018-physical-activity-guidelines-2nd@1"
    ]
    assert by_id["nutrition_knowledge_grounded"].required_knowledge_source_ids == [
        "nih-ods-exercise-athletic-performance-consumer@1"
    ]
    assert not by_id["knowledge_no_evidence"].required_knowledge_source_ids
    assert by_id["knowledge_no_evidence"].forbid_knowledge_citations is True
    assert by_id["rag_prompt_injection"].forbidden_message_fragments


def test_image_evaluation_dataset_uses_private_asset_fixture_keys() -> None:
    dataset_directory = (
        Path(__file__).parents[1]
        / "src"
        / "nxtrep_backend"
        / "evaluation"
        / "datasets"
    )
    cases = load_agent_evaluation_cases(dataset_directory / "image_agent.template.json")
    fixtures = load_agent_asset_fixtures(dataset_directory / "asset_fixtures.example.json")

    mixed_case = next(item for item in cases if item.case_id == "mixed_food_and_body_photos")
    request = resolve_agent_evaluation_request(mixed_case, fixtures)

    assert len(cases) == 5
    assert request.image_asset_ids == [
        fixtures["body_front_photo"],
        fixtures["multi_food_photo"],
    ]


def test_evaluator_accepts_required_confirmation_card() -> None:
    case = AgentEvaluationCase(
        case_id="training_plan_case",
        description="Training plan requires confirmation",
        request={"message": "创建计划"},
        expected_task_types=["training_plan_draft"],
        allowed_response_statuses=["completed"],
        require_confirmation_for=["training_plan_draft"],
    )
    card = confirmation_card()
    response = AgentChatResponse(
        message="草稿等待确认",
        conversation_id=uuid4(),
        analysis_results=[
            AgentBranchResult(
                task_type="training_plan_draft",
                status="completed",
                result={"draft_id": "draft"},
                requires_confirmation=True,
                confirmation_cards=[card],
            )
        ],
        confirmation_cards=[card],
    )

    result = evaluate_agent_response(case, response)

    assert result.passed is True
    assert result.score == 1


def test_evaluator_rejects_unexpected_write_confirmation() -> None:
    case = AgentEvaluationCase(
        case_id="readonly_case",
        description="Read-only query",
        request={"message": "查询训练"},
        expected_task_types=["structured_data_query"],
        forbid_confirmation_for=["structured_data_query"],
    )
    card = confirmation_card()
    response = AgentChatResponse(
        message="查询结果",
        conversation_id=uuid4(),
        analysis_results=[
            AgentBranchResult(
                task_type="structured_data_query",
                status="completed",
                result={"count": 2},
                requires_confirmation=True,
                confirmation_cards=[card],
            )
        ],
        confirmation_cards=[card],
    )

    result = evaluate_agent_response(case, response)

    assert result.passed is False
    assert any(
        check.name == "confirmation_forbidden:structured_data_query" and not check.passed
        for check in result.checks
    )


def test_evaluator_requires_expected_knowledge_sources() -> None:
    case = AgentEvaluationCase(
        case_id="rag_citation_case",
        description="RAG answer cites the expected published source version",
        request={"message": "深蹲时应该怎样呼吸？"},
        expected_task_types=["knowledge_retrieval"],
        required_knowledge_source_ids=["squat-guide@3"],
    )
    response = AgentChatResponse(
        message="下蹲时吸气，起身通过发力点后呼气。",
        conversation_id=uuid4(),
        analysis_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "下蹲时吸气，起身通过发力点后呼气。"},
                citations=[
                    AgentCitation(
                        source_type="knowledge",
                        source_id="squat-guide@3",
                        label="深蹲动作指南 / 呼吸 / 第4页",
                    )
                ],
            )
        ],
        citations=[
            AgentCitation(
                source_type="knowledge",
                source_id="squat-guide@3",
                label="深蹲动作指南 / 呼吸 / 第4页",
            )
        ],
    )

    passing = evaluate_agent_response(case, response)
    failing = evaluate_agent_response(
        case,
        response.model_copy(update={"citations": []}),
    )

    assert passing.passed is True
    assert failing.passed is False
    assert any(
        check.name == "required_knowledge_sources" and not check.passed
        for check in failing.checks
    )


def test_evaluator_rejects_forbidden_knowledge_citations() -> None:
    case = AgentEvaluationCase(
        case_id="rag_no_evidence_case",
        description="No evidence response must not expose a knowledge citation",
        request={"message": "是否有火星低重力训练规则？"},
        expected_task_types=["knowledge_retrieval"],
        forbid_knowledge_citations=True,
    )
    response = AgentChatResponse(
        message="知识库没有足够依据。",
        conversation_id=uuid4(),
        analysis_results=[
            AgentBranchResult(
                task_type="knowledge_retrieval",
                status="completed",
                result={"answer": "知识库没有足够依据。"},
            )
        ],
        citations=[
            AgentCitation(
                source_type="knowledge",
                source_id="invented-source@1",
                label="不存在的资料",
            )
        ],
    )

    result = evaluate_agent_response(case, response)

    assert result.passed is False
    assert any(
        check.name == "knowledge_citations_forbidden" and not check.passed
        for check in result.checks
    )


def test_evaluation_case_rejects_conflicting_knowledge_citation_rules() -> None:
    with pytest.raises(
        ValueError,
        match="required knowledge sources cannot be combined",
    ):
        AgentEvaluationCase(
            case_id="rag_conflicting_citation_rules",
            description="Invalid citation expectations",
            request={"message": "问题"},
            expected_task_types=["knowledge_retrieval"],
            required_knowledge_source_ids=["source@1"],
            forbid_knowledge_citations=True,
        )


def test_report_aggregates_pass_rate_and_mean_score() -> None:
    base_case = AgentEvaluationCase(
        case_id="aggregate_case",
        description="Aggregate scores",
        request={"message": "查询训练"},
        expected_task_types=["structured_data_query"],
    )
    passing_response = AgentChatResponse(
        message="结果",
        conversation_id=uuid4(),
        analysis_results=[
            AgentBranchResult(
                task_type="structured_data_query",
                status="completed",
                result={"count": 1},
            )
        ],
    )
    failing_response = passing_response.model_copy(
        update={
            "analysis_results": [
                AgentBranchResult(
                    task_type="general_question",
                    status="completed",
                    result={"answer": "wrong route"},
                )
            ]
        }
    )

    report = build_agent_evaluation_report(
        [
            evaluate_agent_response(base_case, passing_response),
            evaluate_agent_response(base_case, failing_response),
        ]
    )

    assert report.total_cases == 2
    assert report.passed_cases == 1
    assert report.pass_rate == 0.5
    assert 0.5 < report.mean_score < 1
