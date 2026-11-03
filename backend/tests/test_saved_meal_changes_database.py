import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from nxtrep_backend.db.models import AgentMemory, NutritionEntry, NutritionEntryRevision, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    FoodCreateRequest,
    FoodUpdateRequest,
    NutritionEntryCreateRequest,
    NutritionEntryDeleteRequest,
    NutritionItemInput,
    NutritionSavedEntryRevisionRequest,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import (
    NutritionConflictError,
    NutritionNotFoundError,
    NutritionService,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"meal-edit-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    repo = SqlAlchemyConfirmationRepository(session)
    service = NutritionService(SqlAlchemyNutritionRepository(session), repo)
    food, version = await service.create_food(
        user.id,
        FoodCreateRequest(
            name="验收熟米饭",
            basis_amount_g=100,
            kcal=130,
            protein_g=3,
            carbs_g=28,
            fat_g=1,
        ),
        source="model_estimated",
        confidence="low",
    )
    entry = await service.create_entry(
        user.id,
        NutritionEntryCreateRequest(
            meal_type="lunch",
            eaten_at=datetime.now(UTC),
            notes="保留这条备注",
            items=[
                NutritionItemInput(food_version_id=version.id, amount_g=200),
                NutritionItemInput(
                    name="鸡蛋",
                    amount_g=100,
                    basis_amount_g=100,
                    kcal=150,
                    protein_g=13,
                    carbs_g=1,
                    fat_g=10,
                    source="user_confirmed",
                    confidence="medium",
                ),
            ],
        ),
    )
    return user, service, repo, food, entry


def correction(version=1, index=0):
    return NutritionSavedEntryRevisionRequest(
        expected_version=version,
        changes=[{"item_index": index, "amount_g": 100}],
        reason="米饭实际100克",
    )


@pytest.mark.asyncio
async def test_saved_portion_confirmation_uses_snapshot_even_when_catalog_renamed_updated_deleted():
    async with SessionFactory() as session:
        try:
            user, service, repo, food, entry = await seed(session)
            original = deepcopy(service._entry_snapshot(entry))
            await service.update_food(
                user.id,
                food.id,
                FoodUpdateRequest(
                    name="新名字",
                    kcal=500,
                    basis_amount_g=100,
                    protein_g=3,
                    carbs_g=28,
                    fat_g=1,
                    expected_version=1,
                ),
            )
            await service.delete_food(user.id, food.id, 2)
            card = await service.propose_saved_entry_change(user.id, entry.id, correction())
            assert service._entry_snapshot(entry) == original
            assert card.operation_type == "nutrition_entry_update"
            assert Decimal(card.after["preview"]["totals_before"]["kcal"]) == 410
            assert Decimal(card.after["preview"]["totals_after"]["kcal"]) == 280
            decisions = DatabaseConfirmationService(repo)
            await decisions.approve(user.id, card.id, card.version)
            assert Decimal(entry.totals["kcal"]) == 280 and entry.version == 2
            assert entry.items[1] == original["items"][1]
            assert entry.items[0]["name"] == "验收熟米饭"
            assert (
                entry.items[0]["source"] == "model_estimated"
                and entry.items[0]["confidence"] == "low"
            )
            for key in (
                "food_version_id",
                "basis_amount_g",
                "kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
            ):
                assert entry.items[0][key] == original["items"][0][key]
            assert entry.notes == original["notes"] and entry.meal_type == "lunch"
            with pytest.raises(DatabaseConfirmationConflictError):
                await decisions.approve(user.id, card.id, 1)
            from nxtrep_backend.core.timezones import CHINA_TIMEZONE

            day = entry.eaten_at.astimezone(CHINA_TIMEZONE).date()
            assert Decimal((await service.daily_summary(user.id, day))["consumed"]["kcal"]) == 280
            deletion = await service.create_entry_delete_confirmation(
                user.id,
                entry.id,
                NutritionEntryDeleteRequest(expected_version=2, reason="这一餐是误记"),
            )
            assert entry.deleted_at is None
            await decisions.approve(user.id, deletion.id, deletion.version)
            assert entry.deleted_at is not None
            assert Decimal((await service.daily_summary(user.id, day))["consumed"]["kcal"]) == 0
            assert (
                Decimal((await service.weekly_summary(user.id, day))["daily_average"]["kcal"]) == 0
            )
            rows = list(
                await session.scalars(
                    select(NutritionEntryRevision)
                    .where(NutritionEntryRevision.entry_id == entry.id)
                    .order_by(NutritionEntryRevision.created_at)
                )
            )
            assert len(rows) == 2
            # PostgreSQL now() is shared by this transaction; versions define the order.
            rows.sort(key=lambda revision: revision.old_values["version"])
            assert rows[0].old_values["items"] == original["items"]
            assert rows[1].new_values["deleted_at"] and rows[1].reason == "这一餐是误记"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMemory)
                    .where(AgentMemory.user_id == user.id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["update", "delete"])
@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_rejected_or_cancelled_saved_meal_change_never_updates_entry(action, decision):
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            original = deepcopy(service._entry_snapshot(entry))
            card = (
                await service.propose_saved_entry_change(user.id, entry.id, correction())
                if action == "update"
                else await service.create_entry_delete_confirmation(
                    user.id,
                    entry.id,
                    NutritionEntryDeleteRequest(expected_version=1, reason="误记"),
                )
            )
            commands = DatabaseConfirmationService(repo)
            if decision == "cancel":
                await commands.cancel(user.id, card.id, card.version)
            else:
                await commands.reject(user.id, card.id, card.version, "保留原记录")
            assert service._entry_snapshot(entry) == original and entry.deleted_at is None
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
@pytest.mark.parametrize("action", ["update", "delete"])
async def test_foreign_or_stale_loaded_meal_cannot_be_changed(action):
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            with pytest.raises(NutritionNotFoundError):
                if action == "update":
                    await service.propose_saved_entry_change(uuid4(), entry.id, correction())
                else:
                    await service.create_entry_delete_confirmation(
                        uuid4(),
                        entry.id,
                        NutritionEntryDeleteRequest(expected_version=1, reason="误记"),
                    )
            card = (
                await service.propose_saved_entry_change(user.id, entry.id, correction())
                if action == "update"
                else await service.create_entry_delete_confirmation(
                    user.id,
                    entry.id,
                    NutritionEntryDeleteRequest(expected_version=1, reason="误记"),
                )
            )
            await session.execute(
                update(NutritionEntry)
                .where(NutritionEntry.id == entry.id)
                .values(version=2, notes="其他入口更新")
                .execution_options(synchronize_session=False)
            )
            with pytest.raises(DatabaseConfirmationConflictError, match="旧草稿未生效"):
                await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert entry.version == 2 and entry.notes == "其他入口更新" and entry.deleted_at is None
            assert Decimal(entry.totals["kcal"]) == 410
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["bad_index", "incomplete_snapshot", "negative_other_item"])
async def test_invalid_saved_snapshot_or_index_does_not_create_card(failure):
    async with SessionFactory() as session:
        try:
            user, service, _, _, entry = await seed(session)
            if failure == "incomplete_snapshot":
                items = deepcopy(entry.items)
                del items[0]["kcal"]
                del items[0]["total_kcal"]
                entry.items = items
            elif failure == "negative_other_item":
                items = deepcopy(entry.items)
                items[1]["total_kcal"] = "-1"
                entry.items = items
            original = deepcopy(service._entry_snapshot(entry))
            with pytest.raises(NutritionConflictError):
                await service.propose_saved_entry_change(
                    user.id, entry.id, correction(index=9 if failure == "bad_index" else 0)
                )
            assert service._entry_snapshot(entry) == original
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_legacy_totals_only_snapshot_scales_correctly_across_two_approvals():
    async with SessionFactory() as session:
        try:
            user, service, repo, _, entry = await seed(session)
            items = deepcopy(entry.items)
            for key in ("basis_amount_g", "kcal", "protein_g", "carbs_g", "fat_g"):
                items[0].pop(key, None)
            entry.items = items
            original = deepcopy(items)
            for version, grams, expected_kcal in ((1, 50, 215), (2, 100, 280)):
                body = NutritionSavedEntryRevisionRequest(
                    expected_version=version,
                    changes=[{"item_index": 0, "amount_g": grams}],
                    reason="核对旧版记录份量",
                )
                card = await service.propose_saved_entry_change(user.id, entry.id, body)
                assert Decimal(entry.items[0]["amount_g"]) == (200 if version == 1 else 50)
                await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
                assert Decimal(entry.totals["kcal"]) == expected_kcal
                assert Decimal(entry.items[0]["total_protein_g"]) == Decimal(3) * grams / 100
                assert Decimal(entry.items[0]["total_carbs_g"]) == Decimal(28) * grams / 100
                assert Decimal(entry.items[0]["total_fat_g"]) == Decimal(1) * grams / 100
                assert entry.items[1] == original[1]
                assert entry.items[0]["name"] == original[0]["name"]
                assert entry.items[0]["source"] == original[0]["source"]
                assert "basis_amount_g" not in entry.items[0]
        finally:
            await session.rollback()
