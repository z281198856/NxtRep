"""Real transactions: reference meals, replacements, confirmation and replay."""

import os
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_meal_estimate_revision_database import seed

from nxtrep_backend.agents.tools import AgentToolContext, build_tools
from nxtrep_backend.db.models import Confirmation, NutritionEntry, NutritionEntryRevision
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.schemas.nutrition import NutritionSavedEntryRevisionRequest
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionConflictError

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def vegetable(amount=150):
    return {
        "name": "炒空心菜",
        "amount_g": amount,
        "basis_amount_g": 150,
        "kcal": 100,
        "protein_g": 3,
        "carbs_g": 6,
        "fat_g": 7,
        "source": "model_estimated",
        "confidence": "low",
        "estimate_assumptions": "按普通一小碗约150克及少量油暂估，实际份量和用油有误差。",
    }


def context(user, service, repo, **scope):
    return AgentToolContext(
        user_id=user.id,
        profile_service=MagicMock(),
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=MagicMock(),
        workout_service=MagicMock(),
        nutrition_service=service,
        body_service=MagicMock(),
        memory_service=MagicMock(),
        confirmation_service=DatabaseConfirmationService(repo),
        task_scope=scope,
    )


@pytest.mark.asyncio
async def test_reference_dinner_preserves_lunch_and_replays_one_confirmation():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            lunch = await service.create_entry(user.id, body)
            original = deepcopy(service._entry_snapshot(lunch))
            ctx = context(user, service, repo, _reference_entities={"entry_id": str(lunch.id)})
            tools = {t.name: t for t in build_tools(ctx, groups={"nutrition_draft"})}
            args = {
                "source_entry_id": str(lunch.id),
                "expected_source_version": lunch.version,
                "meal_type": "dinner",
                "eaten_at": (lunch.eaten_at + timedelta(hours=6)).isoformat(),
                "replacements": [{"item_index": 1, **vegetable()}],
                "notes": "晚饭参照午饭换菜",
            }
            tool = tools["propose_nutrition_entry_from_reference"]
            first = await tool.ainvoke(args)
            second = await tool.ainvoke(args)
            assert first == second and first["status"] == "confirmation_required"
            assert ctx.tool_runs[-1]["replayed"] is True
            assert service._entry_snapshot(lunch) == original
            count = await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user.id)
            )
            assert count == 1
            card = first["confirmation"]
            await DatabaseConfirmationService(repo).approve(
                user.id, UUID(card["confirmation_id"]), card["version"]
            )
            rows = list(
                await session.scalars(
                    select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                )
            )
            dinner = next(row for row in rows if row.id != lunch.id)
            assert len(rows) == 2 and dinner.meal_type == "dinner"
            assert dinner.items[0] == lunch.items[0]
            assert dinner.items[2] == lunch.items[2]
            assert dinner.items[1]["name"] == "炒空心菜"
            assert service._entry_snapshot(lunch) == original
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_reference_version_conflict_creates_no_confirmation():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            lunch = await service.create_entry(user.id, body)
            tools = {
                t.name: t
                for t in build_tools(context(user, service, repo), groups={"nutrition_draft"})
            }
            result = await tools["propose_nutrition_entry_from_reference"].ainvoke(
                {
                    "source_entry_id": str(lunch.id),
                    "expected_source_version": lunch.version + 1,
                    "meal_type": "dinner",
                    "eaten_at": lunch.eaten_at.isoformat(),
                    "replacements": [],
                    "notes": "参考版本已过期",
                }
            )
            assert result["error_code"] == "REFERENCE_VERSION_CONFLICT"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Confirmation)
                    .where(Confirmation.user_id == user.id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_saved_food_replacement_is_in_place_confirmed_and_keeps_other_snapshots():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            original = deepcopy(service._entry_snapshot(entry))
            request = NutritionSavedEntryRevisionRequest.model_validate(
                {
                    "expected_version": entry.version,
                    "changes": [
                        {"item_index": 1, "replacement": vegetable()},
                    ],
                    "reason": "原午饭实际吃的是空心菜",
                }
            )
            card = await service.propose_saved_entry_change(user.id, entry.id, request)
            assert card.after["preview"]["changes"][0]["replacement_name"] == "炒空心菜"
            assert service._entry_snapshot(entry) == original
            await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert entry.version == 2 and entry.items[1]["name"] == "炒空心菜"
            assert entry.items[0] == original["items"][0]
            assert entry.items[2] == original["items"][2]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntryRevision)
                    .where(NutritionEntryRevision.entry_id == entry.id)
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_pending_replacement_can_receive_a_later_quantity_correction():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            first = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest.model_validate(
                    {
                        "expected_version": 1,
                        "changes": [{"item_index": 1, "replacement": vegetable()}],
                        "reason": "更正午餐食物",
                    }
                ),
            )
            second = await service.revise_pending_saved_entry(
                user.id,
                first.id,
                first.version,
                entry.id,
                NutritionSavedEntryRevisionRequest.model_validate(
                    {
                        "expected_version": 1,
                        "changes": [{"item_index": 1, "amount_g": 200}],
                        "reason": "菜实际两百克",
                    }
                ),
            )
            assert first.status == "rejected"
            assert second.after["changes"][0]["replacement"]["name"] == "炒空心菜"
            await DatabaseConfirmationService(repo).approve(user.id, second.id, second.version)
            assert Decimal(entry.items[1]["amount_g"]) == 200
            assert entry.items[1]["name"] == "炒空心菜"
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_replacement_and_removal_preview_keeps_original_indices():
    async with SessionFactory() as session:
        try:
            user, service, _, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            card = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest.model_validate(
                    {
                        "expected_version": 1,
                        "changes": [{"item_index": 1, "replacement": vegetable()}],
                        "remove_item_indices": [0],
                        "reason": "移除鸡肉并更正第二项食物",
                    }
                ),
            )
            assert card.after["preview"]["changes"][0]["replacement_name"] == "炒空心菜"
            entry.version = 2
            with pytest.raises(NutritionConflictError, match="已更改"):
                await service.correct_saved_entry(
                    user.id,
                    entry.id,
                    NutritionSavedEntryRevisionRequest.model_validate(
                        {
                            "expected_version": 1,
                            "changes": [{"item_index": 1, "replacement": vegetable()}],
                            "reason": "旧版本不得覆盖",
                        }
                    ),
                )
        finally:
            await session.rollback()
