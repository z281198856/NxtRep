import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.body_vision import BodyImageAssessmentError
from nxtrep_backend.providers.model_errors import VisionModelBusyError
from nxtrep_backend.schemas.agent import (
    AgentBranchResult,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_execution import (
    AgentBranchExecutor,
    AgentBranchHandler,
    AgentBranchInput,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.agent_planning import PlannedAgentRequest


def make_image(purpose: ImagePurpose) -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=purpose,
        content_type="image/jpeg",
        data=b"sanitized-image",
    )


def make_task(task_type: str, asset_ids: list | None = None) -> AgentIntentTask:
    return AgentIntentTask(
        task_type=task_type,
        asset_ids=asset_ids or [],
        confidence="high",
        routing_reason="测试分支执行。",
    )


def make_success(task: AgentIntentTask) -> AgentBranchResult:
    return AgentBranchResult(
        task_type=task.task_type,
        asset_ids=task.asset_ids,
        status="completed",
        result={"message": f"{task.task_type} completed"},
    )


def make_handler() -> MagicMock:
    handler = MagicMock(spec=AgentBranchHandler)
    handler.execute = AsyncMock()
    return handler


class CoordinatedHandler:
    def __init__(
        self,
        *,
        started: list[str],
        all_started: asyncio.Event,
    ) -> None:
        self._started = started
        self._all_started = all_started

    async def execute(
        self,
        branch_input: AgentBranchInput,
    ) -> AgentBranchResult:
        self._started.append(branch_input.task.task_type)

        if len(self._started) == 2:
            self._all_started.set()

        await asyncio.wait_for(
            self._all_started.wait(),
            timeout=1,
        )
        return make_success(branch_input.task)


@pytest.mark.asyncio
async def test_executor_runs_handlers_concurrently_and_preserves_order() -> None:
    body_task = make_task("body_assessment")
    nutrition_task = make_task("nutrition_analysis")
    started: list[str] = []
    all_started = asyncio.Event()
    executor = AgentBranchExecutor(
        {
            "body_assessment": CoordinatedHandler(
                started=started,
                all_started=all_started,
            ),
            "nutrition_analysis": CoordinatedHandler(
                started=started,
                all_started=all_started,
            ),
        }
    )
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[body_task, nutrition_task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="同时分析身体和饮食",
        planned_request=planned,
    )

    assert set(started) == {
        "body_assessment",
        "nutrition_analysis",
    }
    assert [item.task_type for item in result.branch_results] == [
        "body_assessment",
        "nutrition_analysis",
    ]
    assert all(item.status == "completed" for item in result.branch_results)


@pytest.mark.asyncio
async def test_executor_can_serialize_handlers_that_share_one_database_session() -> None:
    active_calls = 0
    maximum_active_calls = 0

    class TrackingHandler:
        async def execute(self, branch_input: AgentBranchInput) -> AgentBranchResult:
            nonlocal active_calls, maximum_active_calls
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)
            await asyncio.sleep(0.01)
            active_calls -= 1
            return make_success(branch_input.task)

    body_task = make_task("body_assessment")
    nutrition_task = make_task("nutrition_analysis")
    handler = TrackingHandler()
    executor = AgentBranchExecutor(
        {
            "body_assessment": handler,
            "nutrition_analysis": handler,
        },
        execution_lock=asyncio.Lock(),
    )
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[body_task, nutrition_task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="同时分析身体和饮食",
        planned_request=planned,
    )

    assert maximum_active_calls == 1
    assert [item.status for item in result.branch_results] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_executor_isolates_one_handler_failure() -> None:
    body_task = make_task("body_assessment")
    nutrition_task = make_task("nutrition_analysis")
    body_handler = make_handler()
    body_handler.execute.return_value = make_success(body_task)
    nutrition_handler = make_handler()
    nutrition_handler.execute.side_effect = RuntimeError("provider secret must not escape")
    executor = AgentBranchExecutor(
        {
            "body_assessment": body_handler,
            "nutrition_analysis": nutrition_handler,
        }
    )
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[body_task, nutrition_task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="同时分析",
        planned_request=planned,
    )

    assert result.branch_results[0].status == "completed"
    failed = result.branch_results[1]
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.code == "BRANCH_EXECUTION_FAILED"
    assert "secret" not in failed.error.message


@pytest.mark.asyncio
async def test_executor_preserves_retryable_vision_capacity_failure() -> None:
    task = make_task("body_assessment")
    handler = make_handler()
    handler.execute.side_effect = VisionModelBusyError("provider overloaded")
    executor = AgentBranchExecutor({"body_assessment": handler})
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="分析体态",
        planned_request=planned,
    )

    failed = result.branch_results[0]
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.code == "VISION_MODEL_BUSY"
    assert failed.error.retryable is True
    assert "繁忙" in failed.error.message


@pytest.mark.asyncio
async def test_executor_preserves_retryable_invalid_vision_assessment() -> None:
    task = make_task("body_assessment")
    handler = make_handler()
    handler.execute.side_effect = BodyImageAssessmentError("invalid fallback JSON")
    executor = AgentBranchExecutor({"body_assessment": handler})
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="分析体态",
        planned_request=planned,
    )

    failed = result.branch_results[0]
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.code == "VISION_ASSESSMENT_INVALID"
    assert failed.error.retryable is True
    assert "重新发送照片" in failed.error.message


@pytest.mark.asyncio
async def test_executor_returns_failure_for_missing_handler() -> None:
    task = make_task("training_plan_draft")
    executor = AgentBranchExecutor({})
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="制定训练计划",
        planned_request=planned,
    )

    failed = result.branch_results[0]
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.code == "BRANCH_NOT_IMPLEMENTED"
    assert failed.error.retryable is False


@pytest.mark.asyncio
async def test_executor_rejects_handler_result_mismatch() -> None:
    body_task = make_task("body_assessment")
    handler = make_handler()
    handler.execute.return_value = AgentBranchResult(
        task_type="nutrition_analysis",
        status="completed",
        result={"message": "wrong branch"},
    )
    executor = AgentBranchExecutor({"body_assessment": handler})
    planned = PlannedAgentRequest(
        images=(),
        intent_plan=AgentIntentPlan(tasks=[body_task]),
    )

    result = await executor.execute(
        user_id=uuid4(),
        message="分析体态",
        planned_request=planned,
    )

    failed = result.branch_results[0]
    assert failed.error is not None
    assert failed.error.code == "BRANCH_RESULT_MISMATCH"


@pytest.mark.asyncio
async def test_executor_passes_only_task_images_to_each_handler() -> None:
    body_image = make_image(ImagePurpose.BODY_PROGRESS)
    meal_image = make_image(ImagePurpose.NUTRITION_ENTRY)
    body_task = make_task("body_assessment", [body_image.asset_id])
    nutrition_task = make_task(
        "nutrition_analysis",
        [meal_image.asset_id],
    )
    body_handler = make_handler()
    body_handler.execute.return_value = make_success(body_task)
    nutrition_handler = make_handler()
    nutrition_handler.execute.return_value = make_success(nutrition_task)
    executor = AgentBranchExecutor(
        {
            "body_assessment": body_handler,
            "nutrition_analysis": nutrition_handler,
        }
    )
    planned = PlannedAgentRequest(
        images=(body_image, meal_image),
        intent_plan=AgentIntentPlan(tasks=[body_task, nutrition_task]),
    )

    await executor.execute(
        user_id=uuid4(),
        message="同时分析身体和饮食",
        planned_request=planned,
    )

    body_input = body_handler.execute.await_args.args[0]
    nutrition_input = nutrition_handler.execute.await_args.args[0]
    assert body_input.images == (body_image,)
    assert nutrition_input.images == (meal_image,)
