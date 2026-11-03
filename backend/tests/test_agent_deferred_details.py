"""Staged conversation input waits for details without bypassing write validation."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_agent_multiturn_pipeline import (
    Pipeline,
    card,
    make_graph,
    route_to,
    tool_context,
)
from test_general_question_branch_handler import make_input, make_react_agent

from nxtrep_backend.agents.prompts import SYSTEM_PROMPT
from nxtrep_backend.agents.synthesis import AgentResponseSynthesizer
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentExecutionBundle
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_handlers.task_action import task_clarification
from nxtrep_backend.services.agent_handlers.training_plan import TrainingPlanBranchHandler


@pytest.mark.asyncio
async def test_deferred_workout_waits_then_completes_same_task_without_invented_sets():
    router = SimpleNamespace(route=AsyncMock(side_effect=[
        route_to("workout_record_draft", {"body_part": "胸", "awaiting_user_details": True}),
        route_to("workout_record_draft", {"exercise_name": "杠铃卧推"}, transition="continue"),
    ]))
    service = SimpleNamespace(propose_record=AsyncMock(return_value=card("workout_record_create")))
    context = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, context), context.user_id)

    first = await pipeline.turn("今天练了胸先帮我创建一个训练记录我再告诉你练了什么")
    task_id = pipeline.task.task_id
    assert first["execution_bundle"].branch_results[0].status == "needs_input"
    assert pipeline.task.current_step == "await_user_details"
    assert set(pipeline.task.missing_fields) == {"exercise_name", "weight_kg", "sets", "reps"}
    assert "等你" in first["response_message"]
    assert not any(
        word in first["response_message"] for word in ("请补充", "公斤", "几组", "已保存", "已创建")
    )
    service.propose_record.assert_not_awaited()

    second = await pipeline.turn("杠铃卧推")
    assert "多少公斤" in second["response_message"]
    assert "awaiting_user_details" not in pipeline.task.parameters
    await pipeline.turn("60kg")
    assert pipeline.task.missing_fields == ["sets", "reps"]
    service.propose_record.assert_not_awaited()
    final = await pipeline.turn("四组每组8次")
    assert pipeline.task.task_id == task_id
    assert pipeline.task.status == "awaiting_confirmation"
    assert len(final["execution_bundle"].branch_results[0].confirmation_cards) == 1
    proposed = service.propose_record.call_args.args[1]
    assert proposed.weight_kg == 60 and proposed.sets == 4 and proposed.reps == 8
    assert "确认生效" not in final["response_message"]


@pytest.mark.asyncio
async def test_cancel_deferred_workout_never_creates_business_record():
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(
        "workout_record_draft", {"awaiting_user_details": True},
    )))
    service = SimpleNamespace(propose_record=AsyncMock())
    context = tool_context(workout_record_service=service)
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    await pipeline.turn("先记着，明细等下发")
    await pipeline.turn("算了，不记了")
    assert pipeline.task.status == "cancelled"
    service.propose_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_plan_does_not_autogenerate_or_report_false_creation():
    agent = make_react_agent({})
    react = GeneralQuestionBranchHandler(lambda _: agent)
    branch = make_input(task_type="training_plan_draft", required_context=[])
    branch = replace(
        branch, message="先留一份训练计划，详细内容等下告诉你",
        task=branch.task.model_copy(update={
            "task_update": AgentTaskUpdate(parameters={"awaiting_user_details": True}),
        }),
    )
    result = await TrainingPlanBranchHandler(react).execute(branch)
    assert result.status == "needs_input" and not result.confirmation_cards
    assert "等你" in result.result["task_answer"]
    assert "已创建" not in result.result["task_answer"]
    agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_defer_does_not_hide_invalid_workout_parameters():
    router = SimpleNamespace(route=AsyncMock(return_value=route_to(
        "workout_record_draft",
        {"exercise_name": "卧推", "weight_kg": -60, "awaiting_user_details": True},
    )))
    context = tool_context(workout_record_service=SimpleNamespace(propose_record=AsyncMock()))
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    result = await pipeline.turn("卧推负60kg，其他稍后给")
    assert "等你" not in result["response_message"]
    assert "weight_kg" in pipeline.task.missing_fields
    assert pipeline.task.current_step == "collect_parameters"
    context.workout_record_service.propose_record.assert_not_awaited()


@pytest.mark.parametrize("fields,question", [
    (["exercise_name", "weight_kg", "sets", "reps"], "这次做了哪些动作？可以一个个告诉我。"),
    (["weight_kg", "sets", "reps"], "用了多少公斤？"),
    (["sets", "reps"], "做了几组，每组多少次？"),
    (["sets"], "做了几组？"),
    (["reps"], "每组多少次？"),
])
def test_workout_clarification_asks_next_useful_question(fields, question):
    assert task_clarification(fields) == question


def test_draft_copy_instructions_keep_confirmation_in_card_and_explain_status_on_request():
    prompt = AgentResponseSynthesizer._messages(
        user_message="帮我记晚饭", execution_bundle=AgentExecutionBundle(branch_results=[
            AgentBranchResult(task_type="general_question", status="completed", result={}),
        ]),
        conversation_context=None,
    )[0].content
    assert "确认流程和保存状态只由卡片展示" in prompt
    assert "不要照抄分支answer或task_answer中的这些流程话术" in prompt
    assert "不能说正式记录已保存" in prompt
    assert "用户明确询问草稿与正式记录差异" in prompt
    assert "不说草稿已创建、已准备好、等待确认等流程话术" in SYSTEM_PROMPT
