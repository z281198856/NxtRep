from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask


def test_agent_intent_task_accepts_structured_multi_workflow_input() -> None:
    asset_id = uuid4()

    task = AgentIntentTask(
        task_type="nutrition_analysis",
        asset_ids=[asset_id],
        required_context=["active_goal", "daily_nutrition_summary"],
        missing_fields=["cooking_oil_amount"],
        confidence="high",
        routing_reason="用户要求分析午餐是否符合减脂目标。",
    )

    assert task.task_type == "nutrition_analysis"
    assert task.asset_ids == [asset_id]
    assert task.required_context == [
        "active_goal",
        "daily_nutrition_summary",
    ]
    assert task.missing_fields == ["cooking_oil_amount"]


def test_agent_intent_task_rejects_unknown_task_type() -> None:
    with pytest.raises(ValidationError, match="unsupported_workflow"):
        AgentIntentTask(
            task_type="unsupported_workflow",
            confidence="low",
            routing_reason="未知工作流不应被接受。",
        )


def test_agent_intent_task_rejects_extra_model_fields() -> None:
    with pytest.raises(ValidationError, match="direct_database_write"):
        AgentIntentTask.model_validate(
            {
                "task_type": "body_assessment",
                "confidence": "medium",
                "routing_reason": "用户请求分析体态。",
                "direct_database_write": True,
            }
        )


def test_agent_intent_task_rejects_blank_routing_reason() -> None:
    with pytest.raises(ValidationError, match="routing_reason"):
        AgentIntentTask(
            task_type="general_question",
            confidence="low",
            routing_reason="",
        )


def test_agent_intent_task_rejects_duplicate_asset_ids() -> None:
    asset_id = uuid4()

    with pytest.raises(ValidationError, match="asset_ids must be unique"):
        AgentIntentTask(
            task_type="body_assessment",
            asset_ids=[asset_id, asset_id],
            confidence="high",
            routing_reason="同一图片在单个任务中只能出现一次。",
        )


def make_task(task_type: str, asset_ids: list) -> AgentIntentTask:
    return AgentIntentTask(
        task_type=task_type,
        asset_ids=asset_ids,
        confidence="high",
        routing_reason="测试多标签路由。",
    )


def test_intent_plan_supports_body_and_nutrition_tasks_together() -> None:
    body_asset_id = uuid4()
    meal_asset_id = uuid4()

    plan = AgentIntentPlan(
        tasks=[
            make_task("body_assessment", [body_asset_id]),
            make_task("nutrition_analysis", [meal_asset_id]),
        ]
    )

    assert [task.task_type for task in plan.tasks] == [
        "body_assessment",
        "nutrition_analysis",
    ]
    assert plan.needs_clarification is False


def test_intent_plan_allows_one_asset_in_multiple_tasks() -> None:
    shared_asset_id = uuid4()

    plan = AgentIntentPlan(
        tasks=[
            make_task("body_assessment", [shared_asset_id]),
            make_task("body_progress_comparison", [shared_asset_id]),
        ]
    )

    assert all(shared_asset_id in task.asset_ids for task in plan.tasks)


def test_intent_plan_rejects_asset_as_assigned_and_unassigned() -> None:
    asset_id = uuid4()

    with pytest.raises(ValidationError, match="assigned and unassigned"):
        AgentIntentPlan(
            tasks=[make_task("body_assessment", [asset_id])],
            unassigned_asset_ids=[asset_id],
        )


def test_intent_plan_requires_questions_when_clarification_needed() -> None:
    with pytest.raises(ValidationError, match="clarification questions"):
        AgentIntentPlan(
            tasks=[make_task("general_question", [])],
            needs_clarification=True,
            clarification_questions=[],
        )


def test_intent_plan_rejects_duplicate_unassigned_asset_ids() -> None:
    asset_id = uuid4()

    with pytest.raises(
        ValidationError,
        match="unassigned_asset_ids must be unique",
    ):
        AgentIntentPlan(
            tasks=[make_task("general_question", [])],
            unassigned_asset_ids=[asset_id, asset_id],
            needs_clarification=True,
            clarification_questions=["这张图片需要分析什么？"],
        )
