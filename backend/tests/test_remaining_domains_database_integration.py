import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import (
    BodyMeasurementRevision,
    CalendarEvent,
    NutritionEntry,
    NutritionTargetVersion,
    TrainingPlanVersion,
    User,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.body import (
    BodyMeasurementCreateRequest,
    BodyMeasurementUpdateRequest,
)
from nxtrep_backend.schemas.nutrition import (
    FoodCreateRequest,
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionTargetDraftRequest,
)
from nxtrep_backend.schemas.workout import (
    WorkoutCreateRequest,
    WorkoutFinishRequest,
    WorkoutSetCreateRequest,
)
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionNotFoundError, NutritionService
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)

OFFICIAL_TEMPLATE_ID = UUID("20000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
async def test_remaining_domains_persist_snapshots_versions_and_confirmations() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            user = User(
                username=f"remaining-domains-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add(user)
            await session.flush()

            confirmations = SqlAlchemyConfirmationRepository(session)
            training = TrainingService(
                SqlAlchemyTrainingRepository(session),
                confirmations,
            )
            draft = await training.create_from_template(user.id, OFFICIAL_TEMPLATE_ID, None)
            confirmation = await training.submit_draft(user.id, draft.id, draft.version)
            approved = await DatabaseConfirmationService(confirmations).approve(
                user.id,
                confirmation.id,
                confirmation.version,
            )

            active_plan = await session.scalar(
                select(TrainingPlanVersion).where(
                    TrainingPlanVersion.user_id == user.id,
                    TrainingPlanVersion.status == "active",
                )
            )
            calendar_count = await session.scalar(
                select(func.count())
                .select_from(CalendarEvent)
                .where(CalendarEvent.user_id == user.id)
            )
            assert approved.status == "succeeded"
            assert active_plan is not None
            assert active_plan.days[0]["exercises"][0]["exercise_id"]
            assert calendar_count == 12

            replacement_draft = await training.create_from_template(
                user.id, OFFICIAL_TEMPLATE_ID, "第二版计划"
            )
            replacement_confirmation = await training.submit_draft(
                user.id, replacement_draft.id, replacement_draft.version
            )
            await DatabaseConfirmationService(confirmations).approve(
                user.id,
                replacement_confirmation.id,
                replacement_confirmation.version,
            )
            active_plan = await session.scalar(
                select(TrainingPlanVersion).where(
                    TrainingPlanVersion.user_id == user.id,
                    TrainingPlanVersion.status == "active",
                )
            )
            calendar_count = await session.scalar(
                select(func.count())
                .select_from(CalendarEvent)
                .where(CalendarEvent.user_id == user.id)
            )
            assert active_plan is not None
            assert active_plan.version == 2
            assert calendar_count == 12

            calendar_event = await session.scalar(
                select(CalendarEvent)
                .where(CalendarEvent.user_id == user.id)
                .order_by(CalendarEvent.scheduled_date, CalendarEvent.created_at)
            )
            assert calendar_event is not None
            assert calendar_event.content_snapshot is not None
            started_at = datetime.now(UTC)
            workouts = WorkoutService(
                SqlAlchemyWorkoutRepository(session),
                SqlAlchemyTrainingRepository(session),
                confirmations,
            )
            aggregate = await workouts.create_workout(
                user.id,
                WorkoutCreateRequest(
                    calendar_event_id=calendar_event.id,
                    started_at=started_at,
                ),
            )
            assert len(aggregate.exercises) == 3
            recorded_set = await workouts.create_set(
                user.id,
                aggregate.workout.id,
                WorkoutSetCreateRequest(
                    client_generated_id=uuid4(),
                    workout_exercise_id=aggregate.exercises[0].id,
                    set_index=1,
                    weight_kg=Decimal("100"),
                    reps=5,
                    rir=2,
                    tags=["working"],
                    completed_at=started_at + timedelta(minutes=5),
                ),
            )
            finished = await workouts.finish_workout(
                user.id,
                aggregate.workout.id,
                WorkoutFinishRequest(
                    ended_at=started_at + timedelta(minutes=60),
                    overall_difficulty=4,
                    fatigue=3,
                    expected_version=aggregate.workout.version,
                ),
            )
            assert recorded_set.version == 1
            assert finished["completed_sets"] == 1
            assert finished["total_volume_kg"] == Decimal("500")
            assert {item["record_type"] for item in finished["prs"]} == {
                "max_weight",
                "max_reps",
            }

            nutrition = NutritionService(SqlAlchemyNutritionRepository(session), confirmations)
            _, food_version = await nutrition.create_food(
                user.id,
                FoodCreateRequest(
                    name="集成测试燕麦",
                    basis_amount_g=Decimal("100"),
                    kcal=Decimal("380"),
                    protein_g=Decimal("13"),
                    carbs_g=Decimal("68"),
                    fat_g=Decimal("7"),
                ),
            )
            entry = await nutrition.create_entry(
                user.id,
                NutritionEntryCreateRequest(
                    meal_type="breakfast",
                    eaten_at=datetime.now(UTC),
                    items=[
                        NutritionItemInput(
                            food_version_id=food_version.id,
                            amount_g=Decimal("50"),
                        )
                    ],
                ),
            )
            assert entry.totals["kcal"] == "190.0"

            other_user = User(
                username=f"private-food-owner-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add(other_user)
            await session.flush()
            _, private_food_version = await nutrition.create_food(
                other_user.id,
                FoodCreateRequest(
                    name="其他用户私有食物",
                    basis_amount_g=Decimal("100"),
                    kcal=Decimal("100"),
                    protein_g=Decimal("10"),
                    carbs_g=Decimal("10"),
                    fat_g=Decimal("2"),
                ),
            )
            with pytest.raises(NutritionNotFoundError):
                await nutrition.create_entry(
                    user.id,
                    NutritionEntryCreateRequest(
                        meal_type="snack",
                        eaten_at=datetime.now(UTC),
                        items=[
                            NutritionItemInput(
                                food_version_id=private_food_version.id,
                                amount_g=Decimal("50"),
                            )
                        ],
                    ),
                )

            target_draft = await nutrition.create_target_draft(
                user.id,
                NutritionTargetDraftRequest(
                    effective_from=date.today(),
                    kcal_min=Decimal("2000"),
                    kcal_max=Decimal("2200"),
                    protein_min_g=Decimal("120"),
                    protein_max_g=Decimal("150"),
                    carbs_min_g=Decimal("200"),
                    carbs_max_g=Decimal("260"),
                    fat_min_g=Decimal("50"),
                    fat_max_g=Decimal("70"),
                ),
            )
            target_confirmation = await nutrition.submit_target(
                user.id,
                target_draft.id,
                target_draft.version,
            )
            await DatabaseConfirmationService(confirmations).approve(
                user.id,
                target_confirmation.id,
                target_confirmation.version,
            )
            active_target = await session.scalar(
                select(NutritionTargetVersion).where(
                    NutritionTargetVersion.user_id == user.id,
                    NutritionTargetVersion.status == "active",
                )
            )
            assert active_target is not None
            assert active_target.values["kcal_min"] == "2000"

            future_target_draft = await nutrition.create_target_draft(
                user.id,
                NutritionTargetDraftRequest(
                    effective_from=date.today() + timedelta(days=7),
                    kcal_min=Decimal("2300"),
                    kcal_max=Decimal("2500"),
                    protein_min_g=Decimal("120"),
                    protein_max_g=Decimal("150"),
                    carbs_min_g=Decimal("240"),
                    carbs_max_g=Decimal("300"),
                    fat_min_g=Decimal("60"),
                    fat_max_g=Decimal("80"),
                ),
            )
            future_confirmation = await nutrition.submit_target(
                user.id,
                future_target_draft.id,
                future_target_draft.version,
            )
            await DatabaseConfirmationService(confirmations).approve(
                user.id,
                future_confirmation.id,
                future_confirmation.version,
            )
            today_summary = await nutrition.daily_summary(user.id, date.today())
            assert today_summary["target"]["kcal_min"] == "2000"
            assert await session.scalar(
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user.id)
            ) == 1

            body = BodyService(SqlAlchemyBodyRepository(session))
            measurement = await body.create_measurement(
                user.id,
                BodyMeasurementCreateRequest(
                    measured_at=datetime.now(UTC),
                    weight_kg=Decimal("75.0"),
                    waist_cm=Decimal("82.0"),
                    body_fat_percent=Decimal("18.5"),
                    body_fat_method="smart_scale",
                    source="manual",
                ),
            )
            updated = await body.update_measurement(
                user.id,
                measurement.id,
                BodyMeasurementUpdateRequest(
                    weight_kg=Decimal("74.8"),
                    reason="修正录入值",
                    expected_version=measurement.version,
                ),
            )
            revision_count = await session.scalar(
                select(func.count())
                .select_from(BodyMeasurementRevision)
                .where(BodyMeasurementRevision.measurement_id == measurement.id)
            )
            assert updated.version == 2
            assert updated.body_fat_percent == Decimal("18.5")
            assert revision_count == 1
        finally:
            await transaction.rollback()
