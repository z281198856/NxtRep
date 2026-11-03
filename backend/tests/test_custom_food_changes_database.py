import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import AgentMemory, FoodVersion, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    CustomFoodPatchRequest,
    FoodCreateRequest,
    FoodUpdateRequest,
    NutritionEntryCreateRequest,
    NutritionItemInput,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionNotFoundError, NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"food-edit-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    commands = SqlAlchemyConfirmationRepository(session)
    nutrition = NutritionService(SqlAlchemyNutritionRepository(session), commands)
    food, version = await nutrition.create_food(
        user.id,
        FoodCreateRequest(
            name="验收燕麦饼",
            brand="自制",
            basis_amount_g=100,
            kcal=300,
            protein_g=10,
            carbs_g=40,
            fat_g=11,
        ),
        source="model_estimated",
        confidence="low",
    )
    return user, nutrition, commands, food, version


@pytest.mark.asyncio
async def test_update_then_delete_only_apply_after_approval_and_preserve_meal_snapshots():
    async with SessionFactory() as session:
        try:
            user, nutrition, commands, food, original = await seed(session)
            meal = await nutrition.create_entry(
                user.id,
                NutritionEntryCreateRequest(
                    meal_type="lunch",
                    eaten_at=datetime.now(UTC),
                    items=[NutritionItemInput(food_version_id=original.id, amount_g=200)],
                ),
            )
            history = deepcopy((meal.items, meal.totals))
            card = await nutrition.propose_custom_food_change(
                user_id=user.id,
                food_id=food.id,
                expected_version=1,
                patch=CustomFoodPatchRequest(kcal=320, notes="每100克热量更正为320，其余保留"),
            )
            assert card.operation_type == "food_update"
            assert card.before["food"]["kcal"] == "300"
            assert card.after["food"]["protein_g"] == "10"
            _, still_old = await nutrition.get_food(user.id, food.id)
            assert still_old.id == original.id and still_old.kcal == 300
            decisions = DatabaseConfirmationService(commands)
            await decisions.approve(user.id, card.id, card.version)
            _, edited = await nutrition.get_food(user.id, food.id)
            assert edited.version == 2 and edited.kcal == 320
            assert edited.confidence == "low" and edited.source == "model_estimated"
            with pytest.raises(DatabaseConfirmationConflictError):
                await decisions.approve(user.id, card.id, 1)
            deletion = await nutrition.propose_custom_food_change(
                user_id=user.id,
                food_id=food.id,
                expected_version=2,
            )
            assert deletion.operation_type == "food_delete"
            assert food.deleted_at is None
            await decisions.approve(user.id, deletion.id, deletion.version)
            assert food.deleted_at is not None
            with pytest.raises(NutritionNotFoundError):
                await nutrition.get_food(user.id, food.id)
            found, total = await nutrition.search_foods(user_id=user.id, keyword="验收燕麦饼")
            assert found == [] and total == 0
            await session.refresh(meal)
            assert (meal.items, meal.totals) == history
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FoodVersion)
                    .where(FoodVersion.food_id == food.id)
                )
                == 2
            )
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
async def test_stale_food_changes_cannot_overwrite_newer_food_version(action):
    async with SessionFactory() as session:
        try:
            user, nutrition, commands, food, _ = await seed(session)
            patch = (
                CustomFoodPatchRequest(kcal=320, notes="更正热量") if action == "update" else None
            )
            card = await nutrition.propose_custom_food_change(
                user_id=user.id,
                food_id=food.id,
                expected_version=1,
                patch=patch,
            )
            await nutrition.update_food(
                user.id,
                food.id,
                FoodUpdateRequest(
                    name=food.name,
                    brand=food.brand,
                    basis_amount_g=100,
                    kcal=350,
                    protein_g=10,
                    carbs_g=40,
                    fat_g=11,
                    expected_version=1,
                ),
            )
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(commands).approve(user.id, card.id, 1)
            _, latest = await nutrition.get_food(user.id, food.id)
            assert latest.version == 2 and latest.kcal == 350
            assert food.deleted_at is None and card.status == "pending"
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["other_user", "public"])
async def test_public_or_foreign_food_never_gets_an_edit_draft(kind):
    async with SessionFactory() as session:
        try:
            user, nutrition, _, food, _ = await seed(session)
            if kind == "public":
                food.owner_user_id = None
            else:
                other = User(username=f"foreign-{uuid4().hex}", password_setup_required=False)
                session.add(other)
                await session.flush()
                food.owner_user_id = other.id
            await session.flush()
            for patch in [None, CustomFoodPatchRequest(name="改名", notes="更名")]:
                with pytest.raises(NutritionNotFoundError):
                    await nutrition.propose_custom_food_change(
                        user_id=user.id,
                        food_id=food.id,
                        expected_version=1,
                        patch=patch,
                    )
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_rejected_or_cancelled_edits_do_not_touch_food(decision):
    async with SessionFactory() as session:
        try:
            user, nutrition, commands, food, _ = await seed(session)
            card = await nutrition.propose_custom_food_change(
                user_id=user.id,
                food_id=food.id,
                expected_version=1,
                patch=CustomFoodPatchRequest(name="新名称", notes="更名"),
            )
            service = DatabaseConfirmationService(commands)
            if decision == "cancel":
                await service.cancel(user.id, card.id, 1)
            else:
                await service.reject(user.id, card.id, 1, "不修改")
            _, latest = await nutrition.get_food(user.id, food.id)
            assert food.name == "验收燕麦饼" and latest.version == 1
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_basis_scales_unspecified_nutrients_and_partial_label_keeps_estimates():
    async with SessionFactory() as session:
        try:
            user, nutrition, _, food, _ = await seed(session)
            card = await nutrition.propose_custom_food_change(
                user_id=user.id,
                food_id=food.id,
                expected_version=1,
                patch=CustomFoodPatchRequest(
                    basis_amount_g=200,
                    kcal=650,
                    brand=None,
                    source="user_provided",
                    confidence="high",
                    notes="每200克650千卡，其余未核对，清空品牌",
                ),
            )
            updated = card.after["food"]
            assert float(updated["kcal"]) == 650
            assert float(updated["protein_g"]) == 20
            assert float(updated["carbs_g"]) == 80
            assert float(updated["fat_g"]) == 22
            assert updated["brand"] is None
            assert updated["confidence"] == "low" and updated["source"] == "model_estimated"
        finally:
            await session.rollback()
