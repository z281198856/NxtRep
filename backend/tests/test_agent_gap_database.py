"""Atomic acceptance using synthetic accounts, rolled back after every case."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_agent_gap_repairs import context, food

from nxtrep_backend.agents.tools import build_tools
from nxtrep_backend.db.models import NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionPendingEntryRevisionRequest,
)
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


@pytest.mark.asyncio
async def test_reference_addition_and_pending_replacement_save_exact_foods_after_approval():
    async with SessionFactory() as session:
        try:
            user = User(username=f"gap-meal-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            confirmations = SqlAlchemyConfirmationRepository(session)
            service = NutritionService(SqlAlchemyNutritionRepository(session), confirmations)
            commands = DatabaseConfirmationService(confirmations)
            original = await service.propose_entry(
                user_id=user.id,
                body=NutritionEntryCreateRequest(
                    meal_type="dinner",
                    eaten_at=datetime.now(UTC),
                    items=[food("鸡腿肉"), food("空心菜"), food("米饭", "190", "247")],
                ),
            )
            await commands.approve(user.id, original.id, original.version)
            source = await service.get_saved_entry(user.id, UUID(original.result["resource_id"]))
            ctx = context(
                user_id=user.id,
                nutrition_service=service,
                task_scope={
                    "_reference_entities": {"entry_id": str(source.id)},
                    "_task_parameters": {"additions": [{"food_name": "蒸蛋"}]},
                },
            )
            tools = {t.name: t for t in build_tools(ctx, groups={"nutrition_draft"})}
            result = await tools["propose_nutrition_entry_from_reference"].ainvoke(
                {
                    "source_entry_id": str(source.id),
                    "expected_source_version": source.version,
                    "meal_type": "dinner",
                    "eaten_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                    "replacements": [],
                    "additions": [food("蒸蛋", "200", "230")],
                    "notes": "额外加一碗蒸蛋",
                }
            )
            assert result["status"] == "confirmation_required"
            pending_id = UUID(result["confirmation"]["confirmation_id"])
            pending = await confirmations.get_confirmation(user.id, pending_id)
            assert (
                len(
                    (
                        await session.scalars(
                            select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                        )
                    ).all()
                )
                == 1
            )
            revised = await service.revise_pending_entry(
                user.id,
                pending_id,
                NutritionPendingEntryRevisionRequest(
                    expected_version=pending.version,
                    changes=[{"item_index": 1, "replacement": food("西兰花", kcal="80")}],
                ),
            )
            assert pending.status == "rejected"
            await commands.approve(user.id, revised.id, revised.version)
            saved = await service.get_saved_entry(user.id, UUID(revised.result["resource_id"]))
            assert [item["name"] for item in saved.items] == ["鸡腿肉", "西兰花", "米饭", "蒸蛋"]
            assert saved.items[2]["amount_g"] == "190"
            assert saved.items[1]["total_kcal"] == "80"
            assert [item["name"] for item in source.items] == ["鸡腿肉", "空心菜", "米饭"]
            assert source.version == 1
        finally:
            await session.rollback()
