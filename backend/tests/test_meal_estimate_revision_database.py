"""Real transactions for reassessing estimated nutrition without changing eaten portions."""

import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from nxtrep_backend.agents.tools.nutrition_changes import build_saved_meal_change_tools
from nxtrep_backend.db.models import NutritionEntry, NutritionEntryRevision, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    FoodCreateRequest,
    NutritionEntryCreateRequest,
    NutritionEstimateCorrection,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionSavedEntryRevisionRequest,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"estimate-revision-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    repository = SqlAlchemyConfirmationRepository(session)
    service = NutritionService(SqlAlchemyNutritionRepository(session), repository)
    _, rice_version = await service.create_food(
        user.id,
        FoodCreateRequest(
            name="虚构验收米饭", basis_amount_g=100, kcal=130, protein_g=3, carbs_g=28, fat_g=0.5
        ),
        source="usda",
        confidence="high",
    )
    body = NutritionEntryCreateRequest(
        meal_type="lunch",
        eaten_at=datetime.now(UTC),
        notes="原份量与时间均须保留",
        items=[
            NutritionItemInput(
                name="虚构鸡肉菜",
                amount_g=200,
                basis_amount_g=200,
                kcal=360,
                protein_g=36,
                carbs_g=6,
                fat_g=22,
                source="model_estimated",
                confidence="low",
            ),
            NutritionItemInput(
                name="虚构豆腐菜",
                amount_g=200,
                basis_amount_g=200,
                kcal=300,
                protein_g=20,
                carbs_g=10,
                fat_g=20,
                source="vision_estimate",
                confidence="low",
            ),
            NutritionItemInput(food_version_id=rice_version.id, amount_g=200),
        ],
    )
    return user, service, repository, body


def estimates():
    return [
        {
            "item_index": 0,
            "nutrition_estimate": {
                "kcal": 280,
                "protein_g": 36,
                "carbs_g": 6,
                "fat_g": 12,
                "assumptions": "按去皮肉和较少烹调用油重估；肉本身脂肪保留，仍有配方误差。",
            },
        },
        {
            "item_index": 1,
            "nutrition_estimate": {
                "kcal": 210,
                "protein_g": 20,
                "carbs_g": 10,
                "fat_g": 10,
                "assumptions": "按非油炸豆腐和较少用油重估，豆腐自身脂肪保留。",
            },
        },
    ]


@pytest.mark.asyncio
async def test_pending_estimates_keep_portions_and_catalog_until_only_new_approval_saves():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            old = await service.propose_entry(user_id=user.id, body=body)
            original = deepcopy(old.after)
            new = await service.revise_pending_entry(
                user.id,
                old.id,
                NutritionPendingEntryRevisionRequest(
                    expected_version=old.version, changes=estimates()
                ),
            )
            assert old.status == "rejected"
            assert new.after["replaces_confirmation_id"] == str(old.id)
            assert new.before == original
            entry = new.after["entry"]
            assert [Decimal(item["amount_g"]) for item in entry["items"]] == [200, 200, 200]
            assert entry["items"][2] == original["entry"]["items"][2]
            assert entry["eaten_at"] == original["entry"]["eaten_at"]
            assert entry["notes"] == original["entry"]["notes"]
            assert Decimal(new.after["preview"]["totals"]["fat_g"]) == 23
            assert Decimal(new.after["preview"]["totals"]["kcal"]) == 750
            assert all(item["confidence"] == "low" for item in entry["items"][:2])
            assert all(item["estimate_assumptions"] for item in entry["items"][:2])
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 0
            )
            decisions = DatabaseConfirmationService(repo)
            with pytest.raises(DatabaseConfirmationConflictError):
                await decisions.approve(user.id, old.id, 1)
            await decisions.approve(user.id, new.id, new.version)
            saved = list(
                await session.scalars(
                    select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                )
            )
            assert len(saved) == 1
            assert Decimal(saved[0].totals["fat_g"]) == 23
            assert saved[0].items[2] == original["preview"]["items"][2]
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_saved_estimates_update_same_meal_only_on_approval_and_keep_revision_history():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            original = deepcopy(service._entry_snapshot(entry))
            card = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=entry.version, changes=estimates(), reason="按少油重估"
                ),
            )
            assert service._entry_snapshot(entry) == original
            preview = card.after["preview"]
            assert Decimal(preview["totals_before"]["fat_g"]) == 43
            assert Decimal(preview["totals_after"]["fat_g"]) == 23
            assert preview["changes"][0]["old_amount_g"] == preview["changes"][0]["amount_g"]
            assert preview["changes"][0]["estimate_assumptions"]
            await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert str(entry.id) == card.after["entry_id"]
            assert entry.version == 2
            assert Decimal(entry.totals["fat_g"]) == 23
            assert entry.items[2] == original["items"][2]
            assert entry.eaten_at.isoformat() == original["eaten_at"]
            revisions = list(
                await session.scalars(
                    select(NutritionEntryRevision).where(
                        NutritionEntryRevision.entry_id == entry.id
                    )
                )
            )
            assert len(revisions) == 1
            assert revisions[0].old_values == original
            assert revisions[0].new_values["items"][0]["estimate_assumptions"]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_saved_pending_revision_preserves_estimate_then_scales_only_explicit_portion():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            original = deepcopy(service._entry_snapshot(entry))
            first = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=entry.version,
                    changes=estimates(),
                    reason="先改少油假设",
                ),
            )
            second = await service.revise_pending_saved_entry(
                user.id,
                first.id,
                first.version,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=entry.version,
                    changes=[{"item_index": 2, "amount_g": 150}],
                    reason="再更正米饭份量",
                ),
            )
            assert first.status == "rejected"
            assert second.after["replaces_confirmation_id"] == str(first.id)
            assert {change["item_index"] for change in second.after["changes"]} == {0, 1, 2}
            third = await service.revise_pending_saved_entry(
                user.id,
                second.id,
                second.version,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=entry.version,
                    changes=[{"item_index": 0, "amount_g": 100}],
                    reason="最后更正肉的份量",
                ),
            )
            assert second.status == "rejected"
            assert service._entry_snapshot(entry) == original
            changes = {change["item_index"]: change for change in third.after["changes"]}
            assert Decimal(changes[0]["nutrition_estimate"]["fat_g"]) == 6
            assert Decimal(changes[1]["nutrition_estimate"]["fat_g"]) == 10
            assert Decimal(changes[2]["amount_g"]) == 150
            decisions = DatabaseConfirmationService(repo)
            with pytest.raises(DatabaseConfirmationConflictError):
                await decisions.approve(user.id, first.id, 1)
            with pytest.raises(DatabaseConfirmationConflictError):
                await decisions.approve(user.id, second.id, 1)
            await decisions.approve(user.id, third.id, third.version)
            assert entry.version == 2
            assert [Decimal(item["amount_g"]) for item in entry.items] == [100, 200, 150]
            assert Decimal(entry.totals["fat_g"]) == Decimal("16.75")
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
async def test_reestimation_after_pending_portion_change_reads_effective_portion_not_saved_base():
    async with SessionFactory() as session:
        try:
            user, service, repo, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            first = await service.propose_saved_entry_change(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=1,
                    changes=[{"item_index": 0, "amount_g": 150}],
                    reason="先修订份量",
                ),
            )
            context = SimpleNamespace(
                user_id=user.id,
                nutrition_service=service,
                confirmation_service=DatabaseConfirmationService(repo),
                task_scope={"confirmation_id": str(first.id)},
            )
            tools = {tool.name: tool for tool in build_saved_meal_change_tools(context)}
            read = await tools["read_saved_meal_for_change"].ainvoke({"entry_id": str(entry.id)})
            selected = read["selected_entry"]
            assert selected["nutrition_state"] == "pending_revision_preview"
            assert Decimal(selected["items"][0]["amount_g"]) == 150
            assert Decimal(entry.items[0]["amount_g"]) == 200
            estimate = {
                "kcal": 200,
                "protein_g": 27,
                "carbs_g": 5,
                "fat_g": 8,
                "assumptions": "实际150克，按少油做法暂估",
            }
            result = await tools["propose_saved_meal_update"].ainvoke(
                {
                    "entry_id": str(entry.id),
                    "request": {
                        "expected_version": 1,
                        "changes": [{"item_index": 0, "nutrition_estimate": estimate}],
                        "reason": "再重估做法",
                    },
                }
            )
            assert result["status"] == "confirmation_required"
            card = result["confirmation"]
            assert first.status == "rejected"
            patch = card["after"]["changes"][0]
            assert Decimal(patch["amount_g"]) == 150
            assert Decimal(patch["nutrition_estimate"]["fat_g"]) == 8
            assert Decimal(entry.items[0]["amount_g"]) == 200
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("protected", ["catalog", "verified"])
async def test_estimate_cannot_overwrite_catalog_or_verified_data_even_in_mixed_patch(
    saved, protected
):
    async with SessionFactory() as session:
        try:
            user, service, _, body = await seed(session)
            index = 2 if protected == "catalog" else 1
            if protected == "verified":
                body.items[1].source = "user_confirmed"
            changes = estimates()
            changes[-1]["item_index"] = index
            if saved:
                entry = await service.create_entry(user.id, body)
                original = deepcopy(service._entry_snapshot(entry))
                with pytest.raises(NutritionConflictError, match="营养依据"):
                    await service.propose_saved_entry_change(
                        user.id,
                        entry.id,
                        NutritionSavedEntryRevisionRequest(
                            expected_version=entry.version, changes=changes, reason="测试保护"
                        ),
                    )
                assert service._entry_snapshot(entry) == original
            else:
                card = await service.propose_entry(user_id=user.id, body=body)
                original = deepcopy(card.after)
                with pytest.raises(NutritionConflictError, match="营养依据"):
                    await service.revise_pending_entry(
                        user.id,
                        card.id,
                        NutritionPendingEntryRevisionRequest(
                            expected_version=card.version, changes=changes
                        ),
                    )
                assert card.after == original and card.status == "pending"
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_combined_amount_and_estimate_uses_totals_once_then_later_portions_scale_new_basis():
    async with SessionFactory() as session:
        try:
            user, service, _, body = await seed(session)
            entry = await service.create_entry(user.id, body)
            patch = estimates()[0]
            patch["amount_g"] = 250
            first = NutritionSavedEntryRevisionRequest(
                expected_version=entry.version, changes=[patch], reason="份量与做法同时纠正"
            )
            await service.correct_saved_entry(user.id, entry.id, first)
            assert entry.items[0]["basis_amount_g"] == "250"
            assert Decimal(entry.items[0]["total_kcal"]) == 280
            await service.correct_saved_entry(
                user.id,
                entry.id,
                NutritionSavedEntryRevisionRequest(
                    expected_version=entry.version,
                    changes=[{"item_index": 0, "amount_g": 125}],
                    reason="再改份量",
                ),
            )
            assert Decimal(entry.items[0]["total_kcal"]) == 140
            assert Decimal(entry.items[0]["total_fat_g"]) == 6
        finally:
            await session.rollback()


@pytest.mark.parametrize("field,value", [("fat_g", -1), ("kcal", "NaN"), ("assumptions", " ")])
def test_estimate_schema_rejects_invalid_values_and_missing_basis(field, value):
    payload = estimates()[0]["nutrition_estimate"] | {field: value}
    with pytest.raises(ValidationError):
        NutritionEstimateCorrection.model_validate(payload)
