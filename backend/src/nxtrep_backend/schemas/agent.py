from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

AgentTaskType = Literal[
    "general_question",
    "body_assessment",
    "body_progress_comparison",
    "body_measurement_draft",
    "memory_write",
    "nutrition_analysis",
    "nutrition_record_draft",
    "training_plan_draft",
    "structured_data_query",
    "knowledge_retrieval",
]

AgentBranchStatus = Literal[
    "completed",
    "needs_input",
    "failed",
]


class AgentBranchError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class AgentContextHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    occurred_at: datetime | None = None
    meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_occurred_at_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("occurred_at must include a timezone offset")
        return value


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8_000)
    conversation_id: UUID | None = None
    image_asset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=4,
    )
    context_hints: AgentContextHints = Field(default_factory=AgentContextHints)

    @field_validator("image_asset_ids")
    @classmethod
    def require_unique_image_assets(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("image_asset_ids must be unique")

        return value


class AgentConfirmationCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: UUID
    operation_type: str
    status: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    impact: str
    expires_at: datetime
    version: int = Field(ge=1)


class AgentCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["structured_data", "image", "knowledge"]
    source_id: str
    label: str


AgentResponseStatus = Literal["completed", "needs_input", "partial", "failed"]
AgentStreamEventType = Literal[
    "run_started",
    "node_completed",
    "message_delta",
    "completed",
    "cancelled",
    "failed",
]


class AgentIntentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: AgentTaskType
    asset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=4,
    )
    required_context: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    confidence: Literal["low", "medium", "high"]
    routing_reason: str = Field(
        min_length=1,
        max_length=500,
    )

    @field_validator("asset_ids")
    @classmethod
    def require_unique_task_asset_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")

        return value


class AgentIntentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[AgentIntentTask] = Field(
        min_length=1,
        max_length=8,
    )
    unassigned_asset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=4,
    )
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(
        default_factory=list,
        max_length=10,
    )

    @model_validator(mode="after")
    def validate_plan(self) -> "AgentIntentPlan":
        if self.needs_clarification and not self.clarification_questions:
            raise ValueError("clarification questions are required")

        assigned_asset_ids = {asset_id for task in self.tasks for asset_id in task.asset_ids}

        if assigned_asset_ids.intersection(self.unassigned_asset_ids):
            raise ValueError("an asset cannot be both assigned and unassigned")

        return self

    @field_validator("unassigned_asset_ids")
    @classmethod
    def require_unique_unassigned_asset_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("unassigned_asset_ids must be unique")

        return value


class AgentBranchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: AgentTaskType
    asset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=4,
    )
    status: AgentBranchStatus
    result: dict[str, Any] | None = None
    operation_results: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    confirmation_cards: list[AgentConfirmationCard] = Field(default_factory=list, max_length=20)
    citations: list[AgentCitation] = Field(default_factory=list, max_length=20)
    missing_fields: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    requires_confirmation: bool = False
    error: AgentBranchError | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "AgentBranchResult":
        if self.status == "completed":
            if self.result is None:
                raise ValueError("completed branch requires result")

            if self.error is not None:
                raise ValueError("completed branch cannot contain error")

        elif self.status == "needs_input":
            if not self.missing_fields:
                raise ValueError("needs_input branch requires missing_fields")

            if self.error is not None:
                raise ValueError("needs_input branch cannot contain error")

        elif self.status == "failed":
            if self.error is None:
                raise ValueError("failed branch requires error")

            if self.result is not None:
                raise ValueError("failed branch cannot contain result")

        return self

    @field_validator("asset_ids")
    @classmethod
    def require_unique_branch_asset_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")

        return value


class AgentExecutionBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_results: list[AgentBranchResult] = Field(
        min_length=1,
        max_length=8,
    )
    unassigned_asset_ids: list[UUID] = Field(
        default_factory=list,
        max_length=4,
    )
    clarification_questions: list[str] = Field(
        default_factory=list,
        max_length=10,
    )

    @field_validator("unassigned_asset_ids")
    @classmethod
    def require_unique_unassigned_asset_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("unassigned_asset_ids must be unique")

        return value

    @model_validator(mode="after")
    def validate_asset_assignments(
        self,
    ) -> "AgentExecutionBundle":
        assigned_asset_ids = {
            asset_id for branch in self.branch_results for asset_id in branch.asset_ids
        }

        if assigned_asset_ids.intersection(self.unassigned_asset_ids):
            raise ValueError("an asset cannot be both assigned and unassigned")

        return self


class AgentChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    conversation_id: UUID
    run_id: UUID | None = None
    status: AgentResponseStatus = "completed"
    analysis_results: list[AgentBranchResult] = Field(default_factory=list)
    confirmation_cards: list[AgentConfirmationCard] = Field(default_factory=list)
    citations: list[AgentCitation] = Field(default_factory=list)


class AgentStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: AgentStreamEventType
    run_id: UUID | None = None
    node: str | None = None
    delta: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    response: AgentChatResponse | None = None
    error_code: str | None = None
    message: str | None = None
