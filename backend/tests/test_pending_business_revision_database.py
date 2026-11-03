"""Shared pending-draft revisions reuse real validators and confirmation execution."""

import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.agents.tools import AgentToolContext, build_tools, groups_for_task
from nxtrep_backend.db.models import BodyMeasurement, Confirmation, Food, Profile, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.agent import AgentIntentTask
from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest
from nxtrep_backend.schemas.nutrition import (
    CustomFoodDraftRequest,
    CustomFoodPatchRequest,
    FoodCreateRequest,
    NutritionTargetDraftRequest,
)
from nxtrep_backend.schemas.profile import ProfileUpdateRequest
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.profile import ProfileService
from nxtrep_backend.services.training import TrainingService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def setup(session, kind):
    user = User(username=f"pending-revision-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    session.add(
        Profile(
            user_id=user.id,
            display_name="虚构验收用户",
            sex="unspecified",
            height_cm=170,
            weekly_training_days=3,
            session_duration_minutes=45,
            experience_level="beginner",
        )
    )
    await session.flush()
    repo = SqlAlchemyConfirmationRepository(session)
    body = BodyService(SqlAlchemyBodyRepository(session), repo)
    profile = ProfileService(
        SqlAlchemyProfileRepository(session), SqlAlchemyBodyRepository(session), repo
    )
    nutrition = NutritionService(SqlAlchemyNutritionRepository(session), repo)
    training = TrainingService(SqlAlchemyTrainingRepository(session), repo)
    task_type = {
        "profile": "profile_update_draft",
        "food_create": "food_catalog_draft",
        "food_update": "food_catalog_draft",
        "body": "body_measurement_draft",
        "target": "nutrition_target_draft",
        "plan": "training_plan_draft",
    }[kind]
    context = AgentToolContext(
        user_id=user.id,
        profile_service=profile,
        goals_service=MagicMock(),
        exercises_service=MagicMock(),
        training_service=training,
        workout_service=MagicMock(),
        nutrition_service=nutrition,
        body_service=body,
        confirmation_service=DatabaseConfirmationService(repo),
        memory_service=MagicMock(),
        task_type=task_type,
    )
    if kind == "profile":
        old = await profile.propose_update(
            user.id, ProfileUpdateRequest(expected_version=1, height_cm=175, weekly_training_days=4)
        )
        changes = {"height_cm": 176}
    elif kind == "food_create":
        old = await nutrition.propose_custom_food(
            user_id=user.id,
            body=CustomFoodDraftRequest(
                name="虚构食品",
                basis_amount_g=100,
                kcal=200,
                protein_g=10,
                carbs_g=20,
                fat_g=8,
                notes="按常见配方暂估",
            ),
        )
        changes = {"fat_g": 6, "kcal": 182, "notes": "修订暂定用油假设"}
    elif kind == "food_update":
        food, version = await nutrition.create_food(
            user.id,
            FoodCreateRequest(
                name="原始虚构食品", basis_amount_g=100, kcal=200, protein_g=10, carbs_g=20, fat_g=8
            ),
        )
        old = await nutrition.propose_custom_food_change(
            user_id=user.id,
            food_id=food.id,
            expected_version=version.version,
            patch=CustomFoodPatchRequest(name="待确认的新名字", fat_g=7, notes="用户提供的更正"),
        )
        changes = {"fat_g": 6}
    elif kind == "body":
        old = await body.propose_measurement(
            user_id=user.id,
            body=BodyMeasurementCreateRequest(
                measured_at=datetime.now(UTC), weight_kg=70, waist_cm=80, source="user_provided"
            ),
        )
        changes = {"weight_kg": 69}
    elif kind == "target":
        draft = await nutrition.create_target_draft(
            user.id,
            NutritionTargetDraftRequest(
                effective_from=date.today(),
                kcal_min=1800,
                kcal_max=2000,
                protein_min_g=100,
                protein_max_g=130,
                carbs_min_g=200,
                carbs_max_g=240,
                fat_min_g=50,
                fat_max_g=65,
            ),
        )
        old = await nutrition.submit_target(user.id, draft.id, draft.version)
        changes = {"fat_max_g": 60}
    else:
        draft = await training.create_suggested_draft(
            user_id=user.id, source="test", template_id=UUID("20000000-0000-4000-8000-000000000001")
        )
        old = await training.submit_draft(user.id, draft.id, draft.version)
        changes = {"name": "修订后的虚构计划"}
    context = replace(context, task_scope={"confirmation_id": str(old.id)}, task_id=uuid4())
    task = AgentIntentTask(task_type=task_type, confidence="high", routing_reason="局部修订验收")
    tools = {tool.name: tool for tool in build_tools(context, groups=groups_for_task(task))}
    return user, context, old, changes, tools


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["profile", "food_create", "food_update", "body", "target", "plan"]
)
async def test_each_pending_draft_is_read_patched_replaced_then_approved_once(kind):
    async with SessionFactory() as session:
        try:
            user, context, old, changes, tools = await setup(session, kind)
            read = await tools["read_pending_business_draft"].ainvoke(
                {"confirmation_id": str(old.id)}
            )
            assert read["status"] == "available"
            before_fields = read["draft"]
            arguments = {
                "confirmation_id": str(old.id),
                "expected_version": old.version,
                "changes": changes,
            }
            result = await tools["propose_pending_draft_revision"].ainvoke(arguments)
            assert result["status"] == "confirmation_required", result
            assert old.status == "rejected"
            card = result["confirmation"]
            assert card["operation_type"] == old.operation_type
            assert card["after"]["replaces_confirmation_id"] == str(old.id)
            assert await tools["propose_pending_draft_revision"].ainvoke(arguments) == result
            if kind == "profile":
                profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
                assert profile.height_cm == 170 and profile.weekly_training_days == 3
                assert card["after"]["changes"] == {"height_cm": "176", "weekly_training_days": 4}
            elif kind.startswith("food"):
                food = card["after"]["food"]
                assert food["protein_g"] == before_fields["protein_g"]
                assert food["name"] == before_fields["name"]
                assert Decimal(food["fat_g"]) == 6
                if kind == "food_create":
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(Food)
                            .where(Food.owner_user_id == user.id)
                        )
                        == 0
                    )
            elif kind == "body":
                assert card["after"]["measurement"]["waist_cm"] == before_fields["waist_cm"]
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(BodyMeasurement)
                        .where(BodyMeasurement.user_id == user.id)
                    )
                    == 0
                )
            elif kind == "target":
                assert result["draft"]["values"]["protein_min_g"] == before_fields["protein_min_g"]
                assert Decimal(result["draft"]["values"]["fat_max_g"]) == 60
                assert await context.nutrition_service.repository.get_active_target(user.id) is None
            else:
                assert result["draft"]["name"] == changes["name"]
                assert len(result["draft"]["days"]) == len(before_fields["days"])
                assert await context.training_service.get_active_plan(user_id=user.id) is None
            with pytest.raises(DatabaseConfirmationConflictError):
                await context.confirmation_service.approve(user.id, old.id, 1)
            approved = await context.confirmation_service.approve(
                user.id, UUID(card["confirmation_id"]), card["version"]
            )
            assert approved.status == "succeeded"
            assert approved.result
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["profile", "food_create", "body", "target", "plan"])
async def test_invalid_patch_preserves_original_card_and_does_not_create_second_proposal(kind):
    async with SessionFactory() as session:
        try:
            user, _, old, _, tools = await setup(session, kind)
            count = await session.scalar(
                select(func.count())
                .select_from(Confirmation)
                .where(Confirmation.user_id == user.id)
            )
            result = await tools["propose_pending_draft_revision"].ainvoke(
                {
                    "confirmation_id": str(old.id),
                    "expected_version": old.version,
                    "changes": {"user_id": str(uuid4())},
                }
            )
            assert result["status"] == "needs_review"
            await session.refresh(old)
            assert old.status == "pending" and old.version == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Confirmation)
                    .where(Confirmation.user_id == user.id)
                )
                == count
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_generic_revision_checks_scope_versions_and_expiry_before_writing():
    async with SessionFactory() as session:
        try:
            _, _, old, changes, tools = await setup(session, "profile")
            proposal = tools["propose_pending_draft_revision"]
            wrong_target = await proposal.ainvoke(
                {"confirmation_id": str(uuid4()), "expected_version": 1, "changes": changes}
            )
            assert wrong_target["error_code"] == "TASK_ENTITY_CONFLICT"
            stale = await proposal.ainvoke(
                {"confirmation_id": str(old.id), "expected_version": 2, "changes": changes}
            )
            assert stale["status"] == "needs_review"
            await session.refresh(old)
            old.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.flush()
            expired = await proposal.ainvoke(
                {"confirmation_id": str(old.id), "expected_version": 1, "changes": changes}
            )
            assert expired["status"] == "needs_review"
            await session.refresh(old)
            assert old.status == "pending"
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_pending_create_gateway_rejects_an_independent_duplicate_and_food_basis_scales_once():
    async with SessionFactory() as session:
        try:
            user, _, old, _, tools = await setup(session, "food_create")
            duplicate = await tools["propose_custom_food"].ainvoke({"food": old.after["food"]})
            assert duplicate["error_code"] == "DRAFT_REVISION_REQUIRED"
            result = await tools["propose_pending_draft_revision"].ainvoke(
                {
                    "confirmation_id": str(old.id),
                    "expected_version": old.version,
                    "changes": {"basis_amount_g": 200},
                }
            )
            food = result["confirmation"]["after"]["food"]
            assert Decimal(food["kcal"]) == 400 and Decimal(food["fat_g"]) == 16
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Confirmation)
                    .where(Confirmation.user_id == user.id, Confirmation.status == "pending")
                )
                == 1
            )
        finally:
            await session.rollback()
