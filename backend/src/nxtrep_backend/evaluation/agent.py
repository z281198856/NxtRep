import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentResponseStatus,
    AgentTaskType,
)


class AgentEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    description: str = Field(min_length=1, max_length=300)
    request: AgentChatRequest
    asset_fixture_keys: list[str] = Field(default_factory=list, max_length=4)
    expected_task_types: list[AgentTaskType] = Field(min_length=1, max_length=8)
    allowed_response_statuses: list[AgentResponseStatus] = Field(
        default_factory=lambda: ["completed", "needs_input", "partial"]
    )
    allow_extra_task_types: bool = False
    require_confirmation_for: list[AgentTaskType] = Field(default_factory=list)
    forbid_confirmation_for: list[AgentTaskType] = Field(default_factory=list)
    forbidden_error_codes: list[str] = Field(default_factory=list)
    forbidden_message_fragments: list[str] = Field(default_factory=list)
    required_knowledge_source_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    forbid_knowledge_citations: bool = False

    @field_validator(
        "expected_task_types",
        "allowed_response_statuses",
        "require_confirmation_for",
        "forbid_confirmation_for",
        "forbidden_error_codes",
        "forbidden_message_fragments",
        "asset_fixture_keys",
        "required_knowledge_source_ids",
    )
    @classmethod
    def require_unique_values(cls, value: list) -> list:
        if len(value) != len(set(value)):
            raise ValueError("evaluation case lists must not contain duplicates")
        return value

    @model_validator(mode="after")
    def reject_two_asset_sources(self) -> "AgentEvaluationCase":
        if self.asset_fixture_keys and self.request.image_asset_ids:
            raise ValueError("use asset_fixture_keys or request.image_asset_ids, not both")
        return self

    @model_validator(mode="after")
    def reject_conflicting_knowledge_citation_rules(
        self,
    ) -> "AgentEvaluationCase":
        if self.required_knowledge_source_ids and self.forbid_knowledge_citations:
            raise ValueError(
                "required knowledge sources cannot be combined with forbidden knowledge citations"
            )

        return self


class AgentEvaluationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    details: str


class AgentEvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    score: float = Field(ge=0, le=1)
    checks: list[AgentEvaluationCheck]


class AgentEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    mean_score: float = Field(ge=0, le=1)
    results: list[AgentEvaluationCaseResult]


def load_agent_evaluation_cases(path: Path) -> list[AgentEvaluationCase]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("Agent evaluation dataset must contain a JSON list")
    cases = [AgentEvaluationCase.model_validate(item) for item in raw_cases]
    case_ids = [item.case_id for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Agent evaluation case_id values must be unique")
    return cases


def load_agent_asset_fixtures(path: Path) -> dict[str, UUID]:
    raw_fixtures = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_fixtures, dict):
        raise ValueError("Agent asset fixtures must contain a JSON object")
    return {str(key): UUID(str(value)) for key, value in raw_fixtures.items()}


def resolve_agent_evaluation_request(
    case: AgentEvaluationCase,
    asset_fixtures: dict[str, UUID],
) -> AgentChatRequest:
    missing = [key for key in case.asset_fixture_keys if key not in asset_fixtures]
    if missing:
        raise ValueError(f"Missing Agent asset fixtures: {', '.join(missing)}")
    if not case.asset_fixture_keys:
        return case.request
    return case.request.model_copy(
        update={
            "image_asset_ids": [asset_fixtures[key] for key in case.asset_fixture_keys],
        }
    )


def evaluate_agent_response(
    case: AgentEvaluationCase,
    response: AgentChatResponse,
) -> AgentEvaluationCaseResult:
    actual_task_types = {item.task_type for item in response.analysis_results}
    expected_task_types = set(case.expected_task_types)
    task_types_passed = (
        expected_task_types <= actual_task_types
        if case.allow_extra_task_types
        else expected_task_types == actual_task_types
    )
    checks = [
        AgentEvaluationCheck(
            name="task_types",
            passed=task_types_passed,
            details=(f"expected={sorted(expected_task_types)}, actual={sorted(actual_task_types)}"),
        ),
        AgentEvaluationCheck(
            name="response_status",
            passed=response.status in case.allowed_response_statuses,
            details=(f"allowed={sorted(case.allowed_response_statuses)}, actual={response.status}"),
        ),
    ]

    actual_error_codes = {
        branch.error.code for branch in response.analysis_results if branch.error is not None
    }
    forbidden_errors = actual_error_codes.intersection(case.forbidden_error_codes)
    if case.required_knowledge_source_ids:
        required_source_ids = set(case.required_knowledge_source_ids)
        actual_source_ids = {
            citation.source_id
            for citation in response.citations
            if citation.source_type == "knowledge"
        }

        checks.append(
            AgentEvaluationCheck(
                name="required_knowledge_sources",
                passed=required_source_ids <= actual_source_ids,
                details=(
                    f"required={sorted(required_source_ids)}, actual={sorted(actual_source_ids)}"
                ),
            )
        )
    if case.forbid_knowledge_citations:
        actual_source_ids = {
            citation.source_id
            for citation in response.citations
            if citation.source_type == "knowledge"
        }

        checks.append(
            AgentEvaluationCheck(
                name="knowledge_citations_forbidden",
                passed=not actual_source_ids,
                details=f"actual={sorted(actual_source_ids)}",
            )
        )
    checks.append(
        AgentEvaluationCheck(
            name="forbidden_error_codes",
            passed=not forbidden_errors,
            details=f"found={sorted(forbidden_errors)}",
        )
    )

    for task_type in case.require_confirmation_for:
        matching = [item for item in response.analysis_results if item.task_type == task_type]
        passed = bool(matching) and all(
            item.requires_confirmation and item.confirmation_cards for item in matching
        )
        checks.append(
            AgentEvaluationCheck(
                name=f"confirmation_required:{task_type}",
                passed=passed,
                details=f"matching_branches={len(matching)}",
            )
        )

    for task_type in case.forbid_confirmation_for:
        matching = [item for item in response.analysis_results if item.task_type == task_type]
        passed = bool(matching) and all(
            not item.requires_confirmation and not item.confirmation_cards for item in matching
        )
        checks.append(
            AgentEvaluationCheck(
                name=f"confirmation_forbidden:{task_type}",
                passed=passed,
                details=f"matching_branches={len(matching)}",
            )
        )

    normalized_message = response.message.casefold()
    found_fragments = [
        fragment
        for fragment in case.forbidden_message_fragments
        if fragment.casefold() in normalized_message
    ]
    checks.append(
        AgentEvaluationCheck(
            name="forbidden_message_fragments",
            passed=not found_fragments,
            details=f"found={found_fragments}",
        )
    )

    passed_count = sum(item.passed for item in checks)
    score = passed_count / len(checks) if checks else 1.0
    return AgentEvaluationCaseResult(
        case_id=case.case_id,
        passed=passed_count == len(checks),
        score=score,
        checks=checks,
    )


def failed_agent_evaluation_case(
    case: AgentEvaluationCase,
    *,
    error_code: str,
) -> AgentEvaluationCaseResult:
    return AgentEvaluationCaseResult(
        case_id=case.case_id,
        passed=False,
        score=0,
        checks=[
            AgentEvaluationCheck(
                name="execution",
                passed=False,
                details=f"error_code={error_code}",
            )
        ],
    )


def build_agent_evaluation_report(
    results: list[AgentEvaluationCaseResult],
) -> AgentEvaluationReport:
    total = len(results)
    passed = sum(item.passed for item in results)
    return AgentEvaluationReport(
        total_cases=total,
        passed_cases=passed,
        pass_rate=passed / total if total else 0,
        mean_score=sum(item.score for item in results) / total if total else 0,
        results=results,
    )
