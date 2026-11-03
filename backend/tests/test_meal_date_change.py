from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from test_agent_multiturn_pipeline import Pipeline, card, make_graph, route_to, tool_context

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.nutrition import NutritionDateChangeRequest
from nxtrep_backend.services.agent_task_parameters import (
    ground_meal_date_parameters,
    normalize_task_parameters,
)


def meal(kind, hour):
    from uuid import uuid4

    return SimpleNamespace(
        id=uuid4(),
        version=1,
        meal_type=kind,
        eaten_at=datetime(2026, 10, 11, hour, tzinfo=UTC),
        items=[{"name": "米饭", "amount_g": "200"}],
        totals={"kcal": "260"},
        notes=None,
    )


def setup(scope=None):
    meals = [meal("lunch", 4), meal("dinner", 10)]
    params = {"action": "change_date", "source_date": "2026-10-11", "target_date": "2026-10-10"}
    if scope:
        params["scope"] = scope
    router = SimpleNamespace(
        route=AsyncMock(return_value=route_to("nutrition_entry_update_draft", params))
    )
    service = SimpleNamespace(
        list_entries=AsyncMock(return_value=meals),
        get_saved_entry=AsyncMock(return_value=meals[0]),
        propose_saved_date_change=AsyncMock(return_value=card("nutrition_entries_date_change")),
    )
    context = tool_context(nutrition_service=service)
    return Pipeline(
        make_graph(router, context), context.user_id,
        occurred_at=datetime(2026, 10, 12, 4, tzinfo=UTC),
    ), service, router, meals


@pytest.mark.asyncio
async def test_day_move_proposes_all_original_ids_without_portion_questions():
    pipeline, service, _, meals = setup("day")
    result = await pipeline.turn("十一号的饮食记错了应该是十号的")
    branch = result["execution_bundle"].branch_results[0]
    assert branch.status == "completed" and branch.requires_confirmation
    assert not branch.missing_fields
    body = service.propose_saved_date_change.call_args.args[1]
    assert body.source_date == date(2026, 10, 11) and body.target_date == date(2026, 10, 10)
    assert {e.entry_id for e in body.entries} == {e.id for e in meals}
    assert pipeline.task.status == "awaiting_confirmation"


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["全部", "午饭", "第一个"])
async def test_ambiguous_move_preserves_dates_through_yes_and_scope_selection(choice):
    pipeline, service, router, meals = setup()
    first = await pipeline.turn("那餐记错日期了，从十一号改成十号")
    task_id = pipeline.task.task_id
    assert first["execution_bundle"].branch_results[0].status == "needs_input"
    assert len(pipeline.task.candidates) == 2
    assert all(c.kind == "meal" for c in pipeline.task.candidates)
    service.propose_saved_date_change.assert_not_awaited()
    await pipeline.turn("是的")
    service.propose_saved_date_change.assert_not_awaited()
    result = await pipeline.turn(choice)
    assert result["execution_bundle"].branch_results[0].status == "completed"
    assert pipeline.task.task_id == task_id
    body = service.propose_saved_date_change.call_args.args[1]
    assert body.source_date == date(2026, 10, 11) and body.target_date == date(2026, 10, 10)
    assert len(body.entries) == (2 if choice == "全部" else 1)
    if choice != "全部":
        assert body.entries[0].entry_id == meals[0].id
    router.route.assert_awaited_once()


def test_relative_previous_day_uses_source_date_not_today():
    valid, invalid = normalize_task_parameters(
        {"source_date": "2026-10-01", "target_date": "前一天"},
        occurred_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert not invalid and valid["target_date"] == "2026-09-30"


@pytest.mark.parametrize(
    "message,source,target",
    [
        ("十一号的饮食记错了应该是十号的", "2026-10-11", "2026-10-10"),
        ("11号的饮食记错了应该是10号的", "2026-10-11", "2026-10-10"),
        ("10月1日的午饭移到前一天", "2026-10-01", "2026-09-30"),
        ("昨天的饮食应该是前天的", "2026-10-11", "2026-10-10"),
    ],
)
def test_explicit_dates_override_incorrect_model_month(message, source, target):
    result = ground_meal_date_parameters(
        message,
        {"action": "change_date", "source_date": "2026-11-11", "target_date": "2026-11-10"},
        {},
        occurred_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert result["source_date"] == source and result["target_date"] == target


@pytest.mark.asyncio
async def test_explicit_date_correction_routes_semantically_but_does_not_approve():
    from test_agent_intent_router import make_dependencies

    from nxtrep_backend.schemas.agent import AgentContextHints, AgentIntentPlan, AgentIntentTask
    from nxtrep_backend.schemas.agent_task import AgentTaskUpdate

    model, structured = make_dependencies()
    structured.ainvoke.return_value = {"parsed": AgentIntentPlan(tasks=[AgentIntentTask(
        task_type="nutrition_entry_update_draft", confidence="high", routing_reason="日期更正",
        task_update=AgentTaskUpdate(transition="new", parameters={
            "action": "change_date", "source_date": "2026-10-11",
            "target_date": "2026-10-10", "scope": "day",
        }),
    )]), "raw": None, "parsing_error": None}
    router = AgentIntentRouter(model)
    plan = await router.route(
        message="十一号的饮食记错了应该是十号的",
        images=[],
        context_hints=AgentContextHints(occurred_at=datetime(2026, 10, 12, tzinfo=UTC)),
    )
    task = plan.tasks[0]
    assert task.task_type == "nutrition_entry_update_draft"
    assert task.task_update.parameters["source_date"] == "2026-10-11"
    assert task.task_update.parameters["target_date"] == "2026-10-10"
    assert task.task_update.parameters["scope"] == "day"
    structured.ainvoke.assert_awaited_once()


def test_date_move_rejects_duplicate_ids_same_dates_and_empty_selection():
    from uuid import uuid4

    entry = {"entry_id": str(uuid4()), "expected_version": 1}
    for entries, target in [
        ([], "2026-10-10"),
        ([entry, entry], "2026-10-10"),
        ([entry], "2026-10-11"),
    ]:
        with pytest.raises(ValidationError):
            NutritionDateChangeRequest(
                source_date="2026-10-11",
                target_date=target,
                entries=entries,
                reason="记错日期",
            )


@pytest.mark.asyncio
async def test_missing_target_only_asks_date_then_accepts_bare_day():
    pipeline, service, router, _ = setup("day")
    initial = {"action": "change_date", "source_date": "2026-10-11", "scope": "day"}
    router.route.return_value = route_to("nutrition_entry_update_draft", initial)
    first = await pipeline.turn("十一号的饮食日期记错了")
    branch = first["execution_bundle"].branch_results[0]
    assert branch.status == "needs_input" and branch.missing_fields == ["target_date"]
    assert "哪一天" in branch.result["task_answer"]
    service.propose_saved_date_change.assert_not_awaited()
    router.route.return_value = route_to(
        "nutrition_entry_update_draft", {"target_date": "2026-11-09"}, transition="continue"
    )
    second = await pipeline.turn("九号")
    assert second["execution_bundle"].branch_results[0].status == "completed"
    assert service.propose_saved_date_change.call_args.args[1].target_date == date(2026, 10, 9)
