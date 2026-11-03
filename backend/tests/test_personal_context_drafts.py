import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.knowledge.schemas import KnowledgeRetrievalHit
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.agent_handlers.knowledge import KnowledgeRetrievalBranchHandler
from nxtrep_backend.services.agent_personal_context import (
    load_personal_context,
    remaining_missing_fields,
)
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError


def tools_for_user(user_id):
    tools = SimpleNamespace(user_id=user_id)
    tools.profile_service = SimpleNamespace(
        get_profile=AsyncMock(
            return_value=SimpleNamespace(
                birth_date=date(2000, 1, 1),
                sex="male",
                height_cm=Decimal("173"),
                timezone="Asia/Shanghai",
                experience_level="beginner",
                weekly_training_days=3,
                session_duration_minutes=45,
            )
        )
    )
    tools.goals_service = SimpleNamespace(
        get_goals_and_constraints=AsyncMock(
            return_value=SimpleNamespace(
                goal=SimpleNamespace(goal_type="muscle_gain"),
                constraints=SimpleNamespace(
                    equipment=["dumbbell"],
                    pain_or_injuries=[],
                    allergies=[],
                    dietary_preferences=[],
                ),
            )
        )
    )
    tools.body_service = SimpleNamespace(
        recent_measurement_summary=AsyncMock(
            return_value={
                "weight_kg": "70",
                "weight_recorded_at": "2026-10-01",
                "body_fat_percent": None,
            }
        )
    )
    return tools


@pytest.mark.asyncio
async def test_context_reads_fresh_authenticated_data_and_calculates_age():
    user = uuid4()
    tools = tools_for_user(user)
    context = await load_personal_context(tools, user)
    assert context["profile"]["age_years"] == datetime.now(ZoneInfo("Asia/Shanghai")).year - 2000
    assert context["profile"]["height_cm"] == "173"
    assert context["measurements"]["weight_kg"] == "70"
    tools.body_service.recent_measurement_summary.return_value["weight_kg"] = "71"
    assert (await load_personal_context(tools, user))["measurements"]["weight_kg"] == "71"
    with pytest.raises(ValueError, match="authenticated"):
        await load_personal_context(tools, uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route", ["general_question", "knowledge_disabled", "knowledge_no_evidence", "knowledge_hits"]
)
async def test_read_only_answer_receives_fresh_profile_even_without_router_context(route):
    user = uuid4()
    tools = tools_for_user(user)
    agent = MagicMock(ainvoke=AsyncMock())
    if route in {"knowledge_no_evidence", "knowledge_hits"}:
        hits = (
            ()
            if route == "knowledge_no_evidence"
            else (
                KnowledgeRetrievalHit(
                    chunk_id=uuid4(),
                    document_id=uuid4(),
                    source_id=uuid4(),
                    source_key="energy-guide",
                    source_title="Energy Guide",
                    source_uri="https://example.com/energy",
                    source_version=1,
                    topic="nutrition",
                    locale="zh-CN",
                    content="每日消耗可根据基础代谢和活动量估算。",
                    section_path="每日能量",
                    page_numbers=(1,),
                    score=0.8,
                    match_type="hybrid",
                ),
            )
        )
        handler = KnowledgeRetrievalBranchHandler(
            SimpleNamespace(retrieve=AsyncMock(return_value=hits)),
            candidate_k=20,
            top_k=5,
            tool_context=tools,
        )
    else:
        handler = GeneralQuestionBranchHandler(
            lambda _: agent,
            tool_context=tools,
            knowledge_retrieval_enabled=False,
        )
    task = AgentIntentTask(
        task_type="general_question" if route == "general_question" else "knowledge_retrieval",
        required_context=[],
        missing_fields=["年龄", "身高", "体重"],
        confidence="high",
        routing_reason="personal calculation without router context",
        task_update=AgentTaskUpdate(missing_fields=["年龄", "身高", "体重"]),
    )
    branch = AgentBranchInput(user_id=user, message="帮我计算我的TDEE", task=task, images=())
    result = await handler.execute(branch)
    assert result.status == "completed"
    assert result.result["personal_context"]["profile"]["height_cm"] == "173"
    assert result.result["personal_context"]["measurements"]["weight_kg"] == "70"
    assert not result.requires_confirmation
    assert result.operation_results == []
    agent.ainvoke.assert_not_awaited()
    tools.body_service.recent_measurement_summary.return_value = {"weight_kg": "71"}
    second = await handler.execute(branch)
    assert second.result["personal_context"]["measurements"]["weight_kg"] == "71"
    assert tools.profile_service.get_profile.await_count == 2
    with pytest.raises(ValueError, match="authenticated"):
        await handler.execute(replace(branch, user_id=uuid4()))


@pytest.mark.asyncio
async def test_missing_profile_is_not_invented_in_fast_answer():
    user = uuid4()
    tools = tools_for_user(user)
    tools.profile_service.get_profile.side_effect = ProfileNotFoundError()
    tools.goals_service.get_goals_and_constraints.side_effect = GoalsNotFoundError()
    tools.body_service.recent_measurement_summary.return_value = {}
    handler = GeneralQuestionBranchHandler(lambda _: None, tool_context=tools)
    result = await handler.execute(
        AgentBranchInput(
            user_id=user,
            message="一个汉堡多少热量",
            images=(),
            task=AgentIntentTask(
                task_type="general_question", confidence="high", routing_reason="food"
            ),
        )
    )
    assert result.status == "completed"
    assert result.result["personal_context"] == {"measurements": {}}


def test_basic_drafts_do_not_require_full_questionnaire_but_keep_safety_questions():
    assert remaining_missing_fields(
        ["age", "height_cm", "weight_kg", "body_fat_percent", "equipment", "injury_clearance"],
        {},
        draft=True,
    ) == ["injury_clearance"]
    assert remaining_missing_fields(
        ["age", "weight_kg"], {"profile": {"age_years": 25}}, draft=False
    ) == ["weight_kg"]


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_available", [True, False])
async def test_nutrition_draft_receives_saved_profile_before_missing_field_gate(profile_available):
    user = uuid4()
    task = AgentIntentTask(
        task_type="nutrition_target_draft",
        confidence="high",
        routing_reason="explicit draft",
        missing_fields=["age", "height_cm", "weight_kg", "body_fat_percent"],
        task_update=AgentTaskUpdate(
            missing_fields=["age", "height_cm", "weight_kg", "body_fat_percent"]
        ),
    )
    branch = AgentBranchInput(
        user_id=user, message="先生成饮食目标草稿，后面再调整", task=task, images=()
    )
    payload = {
        "status": "confirmation_required",
        "confirmation": {
            "confirmation_id": str(uuid4()),
            "operation_type": "nutrition_target_activate",
            "status": "pending",
            "impact": "确认后生效",
            "expires_at": "2099-01-01T00:00:00Z",
            "version": 1,
        },
    }
    agent = MagicMock()
    agent.ainvoke = AsyncMock(
        return_value={
            "messages": [
                ToolMessage(
                    content=json.dumps(payload),
                    name="propose_nutrition_target",
                    tool_call_id="target",
                ),
                AIMessage(content="草稿已创建，确认后生效。"),
            ]
        }
    )
    tools = tools_for_user(user)
    if not profile_available:
        tools.profile_service.get_profile.side_effect = ProfileNotFoundError()
        tools.goals_service.get_goals_and_constraints.side_effect = GoalsNotFoundError()
        tools.body_service.recent_measurement_summary.return_value = {}
    handler = GeneralQuestionBranchHandler(lambda _: agent, tool_context=tools)
    result = await handler.execute(branch)
    assert result.status == "completed" and result.requires_confirmation
    sent = json.loads(agent.ainvoke.await_args.args[0]["messages"][-1]["content"])
    if profile_available:
        assert sent["verified_user_context"]["profile"]["height_cm"] == "173"
        assert sent["verified_user_context"]["measurements"]["weight_kg"] == "70"
    else:
        assert sent["verified_user_context"] == {"measurements": {}}
    tools.profile_service.get_profile.assert_awaited_once_with(user_id=user)
    blocked = await handler.execute(
        replace(branch, task=task.model_copy(update={"missing_fields": ["injury_clearance"]}))
    )
    assert blocked.status == "needs_input"
    assert blocked.missing_fields == ["injury_clearance"]
    assert agent.ainvoke.await_count == 1
