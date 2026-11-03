import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import AgentMemory, Food, NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import CustomFoodDraftRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local database only"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject", "cancel"])
async def test_custom_food_only_saved_on_owner_approval_without_meal_or_memory(decision):
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            owner = User(username=f"custom-food-{uuid4().hex}", password_setup_required=False)
            other = User(username=f"custom-other-{uuid4().hex}", password_setup_required=False)
            session.add_all([owner, other])
            await session.flush()
            confirmations = SqlAlchemyConfirmationRepository(session)
            nutrition = NutritionService(SqlAlchemyNutritionRepository(session), confirmations)
            service = DatabaseConfirmationService(confirmations)
            draft = await nutrition.propose_custom_food(
                user_id=owner.id,
                body=CustomFoodDraftRequest(
                    name="自制燕麦饼",
                    basis_amount_g=100,
                    kcal=300,
                    protein_g=10,
                    carbs_g=40,
                    fat_g=11,
                    notes="每100克暂定估算，请核对配方",
                ),
            )
            assert draft.operation_type == "food_create" and draft.status == "pending"
            assert (
                await session.scalar(
                    select(func.count()).select_from(Food).where(Food.owner_user_id == owner.id)
                )
                == 0
            )
            with pytest.raises(DatabaseConfirmationNotFoundError):
                await service.approve(other.id, draft.id, 1)
            if decision == "approve":
                result = await service.approve(owner.id, draft.id, 1)
                food, version = await nutrition.get_food(owner.id, result.result["resource_id"])
                assert food.name == "自制燕麦饼"
                assert version.basis_amount_g == Decimal(100)
                assert version.source == "model_estimated" and version.confidence == "low"
                with pytest.raises(DatabaseConfirmationConflictError):
                    await service.approve(owner.id, draft.id, 1)
            elif decision == "reject":
                await service.reject(owner.id, draft.id, 1, "不保存")
            else:
                await service.cancel(owner.id, draft.id, 1)
            assert await session.scalar(
                select(func.count()).select_from(Food).where(Food.owner_user_id == owner.id)
            ) == (1 if decision == "approve" else 0)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == owner.id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMemory)
                    .where(AgentMemory.user_id == owner.id)
                )
                == 0
            )
        finally:
            await transaction.rollback()
