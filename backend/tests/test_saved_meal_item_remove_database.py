import os
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from test_saved_meal_changes_database import seed

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import Confirmation, NutritionEntry, NutritionEntryRevision
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.schemas.nutrition import NutritionSavedEntryRevisionRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionNotFoundError

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def removal(*indices, version=1, changes=()):
    return NutritionSavedEntryRevisionRequest(
        expected_version=version,
        remove_item_indices=list(indices),
        changes=list(changes),
        reason="移除这餐中误记的食物",
    )


@pytest.mark.asyncio
async def test_remove_food_only_after_approval_preserves_other_foods_and_recalculates_statistics():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            original = deepcopy(service._entry_snapshot(entry))
            card = await service.propose_saved_entry_change(user.id, entry.id, removal(1))
            assert service._entry_snapshot(entry) == original
            assert card.operation_type == "nutrition_entry_update"
            assert card.after["remove_item_indices"] == [1] and card.after["changes"] == []
            assert card.after["preview"]["removed_items"] == [
                {"item_index": 1, "name": "鸡蛋", "amount_g": original["items"][1]["amount_g"]}
            ]
            assert Decimal(card.after["preview"]["totals_after"]["kcal"]) == 260
            command = DatabaseConfirmationService(repo)
            await command.approve(user.id, card.id, card.version)
            assert entry.version == 2 and entry.deleted_at is None
            assert entry.items == [original["items"][0]]
            assert entry.notes == original["notes"] and entry.meal_type == original["meal_type"]
            assert Decimal(entry.totals["kcal"]) == 260
            assert Decimal(entry.totals["protein_g"]) == 6
            day = entry.eaten_at.astimezone(CHINA_TIMEZONE).date()
            assert Decimal((await service.daily_summary(user.id, day))["consumed"]["kcal"]) == 260
            weekly = await service.weekly_summary(user.id, day)
            assert Decimal(weekly["daily_average"]["kcal"]) == 260
            assert weekly["total_entries"] == 1
            rows = list(
                await session.scalars(
                    select(NutritionEntryRevision).where(
                        NutritionEntryRevision.entry_id == entry.id
                    )
                )
            )
            assert len(rows) == 1
            assert rows[0].old_values["items"] == original["items"]
            assert rows[0].new_values["items"] == entry.items
            with pytest.raises(DatabaseConfirmationConflictError):
                await command.approve(user.id, card.id, 1)
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_multiple_removals_and_portion_change_use_original_item_indices():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            added = deepcopy(entry.items[1])
            added["name"] = "另一份鸡蛋"
            entry.items = [*entry.items, added]
            entry.totals = {
                key: str(Decimal(value) + Decimal(added[f"total_{key}"]))
                for key, value in entry.totals.items()
            }
            card = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                removal(0, 2, changes=[{"item_index": 1, "amount_g": 150}]),
            )
            await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert len(entry.items) == 1
            assert entry.items[0]["name"] == "鸡蛋"
            assert Decimal(entry.items[0]["amount_g"]) == 150
            assert Decimal(entry.totals["kcal"]) == 225
            assert entry.deleted_at is None
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [(9,), (0, 1)])
async def test_invalid_or_entire_meal_removal_creates_no_card_and_leaves_entry_unchanged(indices):
    async with SessionFactory() as session:
        try:
            user, service, _, _, entry = await seed(session)
            original = deepcopy(service._entry_snapshot(entry))
            with pytest.raises(NutritionConflictError) as failure:
                await service.propose_saved_entry_change(user.id, entry.id, removal(*indices))
            if indices == (0, 1):
                assert "删除整餐" in str(failure.value)
            assert service._entry_snapshot(entry) == original
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
async def test_foreign_stale_proposals_and_stale_approval_do_not_remove_food():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            original_items = deepcopy(entry.items)
            with pytest.raises(NutritionNotFoundError):
                await service.propose_saved_entry_change(uuid4(), entry.id, removal(1))
            with pytest.raises(NutritionConflictError):
                await service.propose_saved_entry_change(user.id, entry.id, removal(1, version=2))
            card = await service.propose_saved_entry_change(user.id, entry.id, removal(1))
            await session.execute(
                update(NutritionEntry)
                .where(NutritionEntry.id == entry.id)
                .values(version=2, notes="另一入口修改")
                .execution_options(synchronize_session=False)
            )
            with pytest.raises(DatabaseConfirmationConflictError, match="旧草稿未生效"):
                await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert entry.items == original_items and entry.deleted_at is None
            assert Decimal(entry.totals["kcal"]) == 410
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_unapproved_item_removal_never_changes_business_data(decision):
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            original = deepcopy(service._entry_snapshot(entry))
            card = await service.propose_saved_entry_change(user.id, entry.id, removal(1))
            commands = DatabaseConfirmationService(repo)
            if decision == "reject":
                await commands.reject(user.id, card.id, card.version, "保留原记录")
            else:
                await commands.cancel(user.id, card.id, card.version)
            assert service._entry_snapshot(entry) == original
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntryRevision)
                    .where(NutritionEntryRevision.entry_id == entry.id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_legacy_portion_confirmation_without_removals_still_approves():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            card = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=1,
                    reason="旧版份量卡",
                    changes=[{"item_index": 0, "amount_g": 100}],
                ),
            )
            old_after = dict(card.after)
            old_after.pop("remove_item_indices")
            card.after = old_after
            await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert len(entry.items) == 2 and Decimal(entry.totals["kcal"]) == 280
        finally:
            await session.rollback()
