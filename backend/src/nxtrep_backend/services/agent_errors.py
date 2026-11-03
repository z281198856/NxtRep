"""Public Agent errors without provider responses, credentials or SQL details."""

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from nxtrep_backend.providers.model_errors import is_model_capacity_error
from nxtrep_backend.schemas.agent import AgentBranchError
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
)
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionNotFoundError
from nxtrep_backend.services.training import (
    TrainingConflictError,
    TrainingNotFoundError,
    TrainingValidationError,
)
from nxtrep_backend.services.workout import WorkoutConflictError, WorkoutNotFoundError


def public_agent_error(error: Exception) -> AgentBranchError:
    if is_model_capacity_error(error):
        return AgentBranchError(
            code="MODEL_BUSY", message="AI 服务当前繁忙，请稍后重试。", retryable=True
        )
    current: BaseException | None = error
    visited: set[int] = set()
    invalid_output = False
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        name = type(current).__name__
        if name == "AgentTaskCapacityError":
            return AgentBranchError(
                code="TASK_CAPACITY_LIMIT", message=str(current), retryable=False
            )
        if name == "IdempotencyKeyConflictError":
            return AgentBranchError(
                code="AGENT_TURN_CONFLICT",
                message="同一个请求标识不能用于不同内容，请发送新的请求。",
                retryable=False,
            )
        if name in {"IdempotencyRequestInProgressError", "AgentTurnInProgressError"}:
            return AgentBranchError(
                code="AGENT_TURN_IN_PROGRESS",
                message="这条请求仍在处理，请稍后核实上次结果。",
                retryable=True,
            )
        if name == "AgentTurnReplayError":
            return AgentBranchError(code=current.error_code, message=str(current), retryable=False)
        if name == "AgentRunInProgressError":
            return AgentBranchError(
                code="AGENT_CONVERSATION_BUSY",
                message="这个会话还在处理上一条消息，请等待完成后再继续。",
                retryable=True,
            )
        if name == "GraphRecursionError":
            return AgentBranchError(
                code="AGENT_STEP_LIMIT",
                message="本次工具处理达到步骤上限，未能完成请求；请核对待确认草稿后重试。",
                retryable=True,
            )
        if name in {
            "GeneralQuestionResponseError",
            "AgentIntentRoutingError",
            "AgentResponseSynthesisError",
            "AgentWorkflowResultError",
        }:
            invalid_output |= any(
                marker in str(current).lower()
                for marker in (
                    "returned no",
                    "empty response",
                    "structured output",
                    "deltas do not match",
                )
            )
        if isinstance(current, TrainingValidationError):
            messages = {item.get("message") for item in current.errors}
            message = (
                "目标日期已有训练，请选择其他日期或明确提出合并安排。"
                if "target date already has a workout" in messages
                else "训练调整不符合业务校验，请核对日期、训练内容和警告后重试。"
            )
            return AgentBranchError(
                code="BUSINESS_RULE_VIOLATION", message=message, retryable=False
            )
        if isinstance(
            current,
            (
                TrainingConflictError,
                WorkoutConflictError,
                NutritionConflictError,
                DatabaseConfirmationConflictError,
            ),
        ):
            return AgentBranchError(
                code="BUSINESS_STATE_CONFLICT",
                message="记录状态已变化或不适用，请刷新相关记录后重新生成草稿。",
                retryable=False,
            )
        if isinstance(
            current,
            (
                TrainingNotFoundError,
                WorkoutNotFoundError,
                NutritionNotFoundError,
                DatabaseConfirmationNotFoundError,
            ),
        ):
            return AgentBranchError(
                code="RECORD_NOT_FOUND",
                message="没有找到对应记录，请核对要操作的训练或食物。",
                retryable=False,
            )
        if isinstance(current, (TimeoutError, httpx.TimeoutException)) or name == "APITimeoutError":
            return AgentBranchError(
                code="AGENT_TIMEOUT",
                message="本次处理超时，尚未确认操作结果，请稍后核对记录再重试。",
                retryable=True,
            )
        if (
            isinstance(current, (ConnectionError, httpx.NetworkError))
            or name == "APIConnectionError"
        ):
            return AgentBranchError(
                code="AGENT_NETWORK_ERROR",
                message="AI 服务连接失败，请稍后重试。",
                retryable=True,
            )
        if isinstance(current, SQLAlchemyError):
            return AgentBranchError(
                code="DATA_ACCESS_FAILED",
                message="暂时无法读取或处理数据，请稍后核对记录再重试。",
                retryable=True,
            )
        if isinstance(current, ValidationError):
            return AgentBranchError(
                code="AGENT_RESULT_INVALID",
                message="返回内容未通过校验，暂时无法完成这项请求。",
                retryable=True,
            )
        if getattr(current, "status_code", None) in {401, 403}:
            return AgentBranchError(
                code="MODEL_ACCESS_DENIED",
                message="AI 服务配置或访问权限异常，需检查后端配置。",
                retryable=False,
            )
        current = current.__cause__ or current.__context__
    if invalid_output:
        return AgentBranchError(
            code="AGENT_RESULT_INVALID",
            message="AI 返回内容不完整，暂时无法可靠完成这项请求，请稍后重试。",
            retryable=True,
        )
    return AgentBranchError(
        code="BRANCH_EXECUTION_FAILED",
        message="这项请求处理失败，尚未确认操作结果，请核对后重试。",
        retryable=True,
    )
