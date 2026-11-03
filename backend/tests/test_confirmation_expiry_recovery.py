"""Expired date drafts must not block a fresh, revalidated user proposal."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from test_agent_multiturn_pipeline import card, tool_context
from test_meal_date_change import setup

from nxtrep_backend.services.conversation import AgentConversationContext


def bind_old(pipeline, old):
    pipeline.context = AgentConversationContext(task_state={"active_task": {
        "task_type": "nutrition_entry_update_draft", "status": "collecting",
        "parameters": {"action": "change_date", "source_date": "2026-10-11",
                       "target_date": "2026-10-10", "scope": "day"},
        "entities": {"confirmation_id": str(old.id)},
    }})

@pytest.mark.asyncio
@pytest.mark.parametrize("stored_status", ["pending", "expired"])
async def test_expired_date_draft_creates_fresh_card_only_after_latest_meal_read(stored_status):
    pipeline, service, _, meals = setup("day")
    old = card("nutrition_entries_date_change", {"request": {
        "source_date": "2026-10-11", "target_date": "2026-10-10",
    }})
    old.status, old.expires_at = stored_status, datetime.now(UTC) - timedelta(hours=1)
    context = tool_context(
        user_id=pipeline.user_id,
        nutrition_service=service,
        confirmation_service=type("Confirmations", (), {"get": AsyncMock(return_value=old)})(),
    )
    from test_agent_multiturn_pipeline import Pipeline, make_graph, route_to

    router = type("Router", (), {"route": AsyncMock(return_value=route_to(
        "nutrition_entry_update_draft",
        {"action": "change_date", "source_date": "2026-10-11",
         "target_date": "2026-10-10", "scope": "day"},
        entities={"confirmation_id": str(old.id)},
    ))})()
    pipeline = Pipeline(
        make_graph(router, context), context.user_id,
        occurred_at=datetime(2026, 10, 12, 4, tzinfo=UTC),
    )
    bind_old(pipeline, old)
    # The saved meal changed while the old draft was waiting. Re-read its new version.
    meals[0].version = 2
    result = await pipeline.turn("十一号的饮食记错了应该是十号的")
    branch = result["execution_bundle"].branch_results[0]
    assert branch.status == "completed" and branch.requires_confirmation
    service.list_entries.assert_awaited_once()
    body = service.propose_saved_date_change.call_args.args[1]
    assert {e.entry_id: e.expected_version for e in body.entries} == {
        m.id: m.version for m in meals
    }
    assert service.propose_saved_date_change.call_args.kwargs == {}
    assert branch.confirmation_cards[0].confirmation_id != old.id
    assert pipeline.task.status == "awaiting_confirmation"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "rejected", "failed"])
async def test_other_closed_cards_are_not_silently_revived(status):
    from test_agent_multiturn_pipeline import Pipeline, make_graph, route_to

    pipeline, service, _, _ = setup("day")
    old = card("nutrition_entries_date_change")
    old.status = status
    confirmations = type("Confirmations", (), {"get": AsyncMock(return_value=old)})()
    context = tool_context(nutrition_service=service, confirmation_service=confirmations)
    router = type("Router", (), {"route": AsyncMock(return_value=route_to(
        "nutrition_entry_update_draft",
        {"action": "change_date", "source_date": "2026-10-11",
         "target_date": "2026-10-10", "scope": "day"},
        entities={"confirmation_id": str(old.id)},
    ))})()
    pipeline = Pipeline(make_graph(router, context), context.user_id)
    bind_old(pipeline, old)
    result = await pipeline.turn("十一号的饮食记错了应该是十号的")
    assert not result["execution_bundle"].branch_results[0].confirmation_cards
    service.propose_saved_date_change.assert_not_awaited()
