import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from nxtrep_backend.agents.body_vision import BodyImageAssessmentError
from nxtrep_backend.providers.model_errors import VisionModelBusyError
from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentContextHints,
    AgentExecutionBundle,
    AgentIntentTask,
    AgentTaskType,
)
from nxtrep_backend.services.agent_context import (
    ActiveMemoryContext,
    AgentContextAssembler,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.agent_planning import PlannedAgentRequest
from nxtrep_backend.services.conversation import AgentConversationContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentBranchInput:
    user_id: UUID
    message: str
    task: AgentIntentTask
    images: tuple[ResolvedAgentImage, ...]
    conversation_context: AgentConversationContext = AgentConversationContext()
    memories: tuple[ActiveMemoryContext, ...] = ()
    context_hints: AgentContextHints = field(default_factory=AgentContextHints)
    prior_results: tuple[AgentBranchResult, ...] = ()


class AgentBranchHandler(Protocol):
    async def execute(
        self,
        branch_input: AgentBranchInput,
    ) -> AgentBranchResult: ...


class AgentBranchExecutor:
    def __init__(
        self,
        handlers: Mapping[
            AgentTaskType,
            AgentBranchHandler,
        ],
        *,
        execution_lock: asyncio.Lock | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._execution_lock = execution_lock

    async def execute(
        self,
        *,
        user_id: UUID,
        message: str,
        planned_request: PlannedAgentRequest,
    ) -> AgentExecutionBundle:
        images_by_id = {image.asset_id: image for image in planned_request.images}

        indexed_tasks = list(enumerate(planned_request.intent_plan.tasks))
        dependent_types = {"nutrition_record_draft"}
        primary_tasks = [
            (index, task) for index, task in indexed_tasks if task.task_type not in dependent_types
        ]
        dependent_tasks = [
            (index, task) for index, task in indexed_tasks if task.task_type in dependent_types
        ]

        primary_results = await asyncio.gather(
            *[
                self._execute_task(
                    user_id=user_id,
                    message=message,
                    task=task,
                    images_by_id=images_by_id,
                    conversation_context=planned_request.conversation_context,
                    memories=planned_request.memories,
                    context_hints=planned_request.context_hints,
                    prior_results=(),
                )
                for _, task in primary_tasks
            ]
        )
        prior_results = tuple(primary_results)
        dependent_results = await asyncio.gather(
            *[
                self._execute_task(
                    user_id=user_id,
                    message=message,
                    task=task,
                    images_by_id=images_by_id,
                    conversation_context=planned_request.conversation_context,
                    memories=planned_request.memories,
                    context_hints=planned_request.context_hints,
                    prior_results=prior_results,
                )
                for _, task in dependent_tasks
            ]
        )
        results_by_index = {
            index: result for (index, _), result in zip(primary_tasks, primary_results, strict=True)
        }
        results_by_index.update(
            {
                index: result
                for (index, _), result in zip(
                    dependent_tasks,
                    dependent_results,
                    strict=True,
                )
            }
        )
        branch_results = [results_by_index[index] for index, _ in indexed_tasks]

        return AgentExecutionBundle(
            branch_results=list(branch_results),
            unassigned_asset_ids=(planned_request.intent_plan.unassigned_asset_ids),
            clarification_questions=(planned_request.intent_plan.clarification_questions),
        )

    async def _execute_task(
        self,
        *,
        user_id: UUID,
        message: str,
        task: AgentIntentTask,
        images_by_id: Mapping[
            UUID,
            ResolvedAgentImage,
        ],
        conversation_context: AgentConversationContext,
        memories: tuple[ActiveMemoryContext, ...],
        context_hints: AgentContextHints,
        prior_results: tuple[AgentBranchResult, ...],
    ) -> AgentBranchResult:
        handler = self._handlers.get(task.task_type)

        if handler is None:
            return self._failed_result(
                task,
                code="BRANCH_NOT_IMPLEMENTED",
                message="This Agent capability is not available",
                retryable=False,
            )

        try:
            task_images = tuple(images_by_id[asset_id] for asset_id in task.asset_ids)
        except KeyError:
            return self._failed_result(
                task,
                code="BRANCH_IMAGE_NOT_FOUND",
                message="A routed image is not available",
                retryable=False,
            )

        branch_input = AgentBranchInput(
            user_id=user_id,
            message=message,
            task=task,
            images=task_images,
            conversation_context=conversation_context,
            memories=AgentContextAssembler.for_task(
                task,
                memories,
            ),
            context_hints=context_hints,
            prior_results=prior_results,
        )

        try:
            if self._execution_lock is None:
                result = await handler.execute(branch_input)
            else:
                async with self._execution_lock:
                    result = await handler.execute(branch_input)
        except VisionModelBusyError:
            logger.warning(
                "Vision model capacity exhausted",
                extra={
                    "agent_task_type": task.task_type,
                    "agent_user_id": str(user_id),
                },
            )
            return self._failed_result(
                task,
                code="VISION_MODEL_BUSY",
                message="视觉评估服务当前繁忙，请稍后重试",
                retryable=True,
            )
        except BodyImageAssessmentError:
            logger.warning(
                "Vision model returned an incomplete assessment",
                extra={
                    "agent_task_type": task.task_type,
                    "agent_user_id": str(user_id),
                },
                exc_info=True,
            )
            return self._failed_result(
                task,
                code="VISION_ASSESSMENT_INVALID",
                message="视觉模型未能返回完整评估结果，请重新发送照片后重试",
                retryable=True,
            )
        except Exception:
            logger.exception(
                "Agent branch execution failed",
                extra={
                    "agent_task_type": task.task_type,
                    "agent_user_id": str(user_id),
                },
            )
            return self._failed_result(
                task,
                code="BRANCH_EXECUTION_FAILED",
                message="This Agent capability failed",
                retryable=True,
            )

        if result.task_type != task.task_type or result.asset_ids != task.asset_ids:
            return self._failed_result(
                task,
                code="BRANCH_RESULT_MISMATCH",
                message="Branch result does not match its task",
                retryable=False,
            )

        return result

    @staticmethod
    def _failed_result(
        task: AgentIntentTask,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> AgentBranchResult:
        return AgentBranchResult(
            task_type=task.task_type,
            asset_ids=task.asset_ids,
            status="failed",
            error=AgentBranchError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )
