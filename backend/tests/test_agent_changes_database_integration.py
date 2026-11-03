"""Exercise Agent proposals against PostgreSQL; all test data rolls back."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.agents.tools.nutrition import build_nutrition_draft_tools
from nxtrep_backend.agents.tools.training import build_training_draft_tools
from nxtrep_backend.agents.tools.workout import build_workout_draft_tools
from nxtrep_backend.db.models import CalendarEvent, NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.training import CompressionDraftCreateRequest
from nxtrep_backend.schemas.workout import (
    WorkoutCreateRequest,
    WorkoutFinishRequest,
    WorkoutSetCreateRequest,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.training import TrainingService, TrainingValidationError
from nxtrep_backend.services.workout import WorkoutConflictError, WorkoutService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Requires local PostgreSQL",
)
TEMPLATE_ID = UUID("20000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("basis,kcal", [("per_basis", "435"), ("total_consumed", "870")])
async def test_custom_meal_portion_units_are_not_multiplied_twice(basis, kcal):
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            user = User(username=f"meal-units-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            repository = SqlAlchemyConfirmationRepository(session)
            nutrition = NutritionService(SqlAlchemyNutritionRepository(session), repository)
            context = SimpleNamespace(user_id=user.id, nutrition_service=nutrition)
            tool = next(
                t
                for t in build_nutrition_draft_tools(context)
                if t.name == "propose_nutrition_entry"
            )
            meal = await tool.ainvoke(
                {
                    "meal_type": "lunch",
                    "eaten_at": datetime.now(UTC).isoformat(),
                    "items": [
                        {
                            "name": "两份测试成品",
                            "amount_g": "330",
                            "basis_amount_g": "165",
                            "kcal": kcal,
                            "protein_g": "0",
                            "carbs_g": "0",
                            "fat_g": "0",
                            "source": "model_estimated",
                            "confidence": "low",
                            "nutrient_basis": basis,
                        }
                    ],
                }
            )
            assert Decimal(meal["draft"]["totals"]["kcal"]) == Decimal("870")
            card = meal["confirmation"]
            await DatabaseConfirmationService(repository).approve(
                user.id, UUID(card["confirmation_id"]), card["version"]
            )
            entries = (
                await session.scalars(
                    select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                )
            ).all()
            assert len(entries) == 1
            assert Decimal(entries[0].totals["kcal"]) == Decimal("870")
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_agent_meal_and_schedule_only_change_data_after_confirmation():
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            user = User(username=f"agent-proposals-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            repository = SqlAlchemyConfirmationRepository(session)
            approvals = DatabaseConfirmationService(repository)
            training = TrainingService(SqlAlchemyTrainingRepository(session), repository)
            nutrition = NutritionService(SqlAlchemyNutritionRepository(session), repository)
            context = SimpleNamespace(
                user_id=user.id, training_service=training, nutrition_service=nutrition
            )
            meal_tool = next(
                t
                for t in build_nutrition_draft_tools(context)
                if t.name == "propose_nutrition_entry"
            )
            meal = await meal_tool.ainvoke(
                {
                    "meal_type": "lunch",
                    "eaten_at": datetime.now(UTC).isoformat(),
                    "items": [
                        {
                            "name": "测试鸡蛋",
                            "amount_g": 100,
                            "basis_amount_g": 100,
                            "kcal": 140,
                            "protein_g": 13,
                            "carbs_g": 1,
                            "fat_g": 9,
                            "source": "official",
                            "confidence": "high",
                        }
                    ],
                    "notes": "按两个鸡蛋去壳共100克估算，可修改后再确认",
                }
            )
            count = (
                select(func.count())
                .select_from(NutritionEntry)
                .where(NutritionEntry.user_id == user.id)
            )
            assert await session.scalar(count) == 0
            assert meal["draft"]["items"][0]["source"] == "model_estimated"
            assert Decimal(meal["draft"]["totals"]["kcal"]) == Decimal("140")
            card = meal["confirmation"]
            approved = await approvals.approve(
                user.id, UUID(card["confirmation_id"]), card["version"]
            )
            assert approved.status == "succeeded"
            assert await session.scalar(count) == 1
            # Retrying the same approval must not create a second meal.
            with pytest.raises(DatabaseConfirmationConflictError):
                await approvals.approve(user.id, approved.id, approved.version)
            assert await session.scalar(count) == 1

            plan = await training.create_from_template(user.id, TEMPLATE_ID, None)
            activation = await training.submit_draft(user.id, plan.id, plan.version)
            await approvals.approve(user.id, activation.id, activation.version)
            events = list(
                (
                    await session.scalars(
                        select(CalendarEvent)
                        .where(CalendarEvent.user_id == user.id)
                        .order_by(CalendarEvent.scheduled_date)
                    )
                ).all()
            )
            source_date = events[0].scheduled_date
            target_date = max(e.scheduled_date for e in events) + timedelta(days=2)
            schedule = next(
                t
                for t in build_training_draft_tools(context)
                if t.name == "propose_schedule_change"
            )
            with pytest.raises(TrainingValidationError):
                await schedule.ainvoke(
                    {
                        "missed_event_id": str(events[0].id),
                        "strategy": "shift",
                        "target_date": events[1].scheduled_date.isoformat(),
                    }
                )
            proposal = await schedule.ainvoke(
                {
                    "missed_event_id": str(events[0].id),
                    "strategy": "shift",
                    "target_date": target_date.isoformat(),
                }
            )
            assert events[0].scheduled_date == source_date
            card = proposal["confirmation"]
            await approvals.approve(user.id, UUID(card["confirmation_id"]), card["version"])
            await session.refresh(events[0])
            assert events[0].scheduled_date == target_date
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("pain,interrupted", [(True, False), (False, True), (False, False)])
async def test_agent_progression_uses_recorded_sets_and_preserves_safety(pain, interrupted):
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            user = User(username=f"agent-progression-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            repository = SqlAlchemyConfirmationRepository(session)
            approvals = DatabaseConfirmationService(repository)
            training_repository = SqlAlchemyTrainingRepository(session)
            training = TrainingService(training_repository, repository)
            draft = await training.create_from_template(user.id, TEMPLATE_ID, None)
            activation = await training.submit_draft(user.id, draft.id, draft.version)
            await approvals.approve(user.id, activation.id, activation.version)
            original_plan = await training_repository.get_active_plan(user.id)
            event = await session.scalar(
                select(CalendarEvent)
                .where(CalendarEvent.user_id == user.id)
                .order_by(CalendarEvent.scheduled_date)
            )
            workouts = WorkoutService(
                SqlAlchemyWorkoutRepository(session), training_repository, repository
            )
            started = datetime.now(UTC)
            aggregate = await workouts.create_workout(
                user.id, WorkoutCreateRequest(calendar_event_id=event.id, started_at=started)
            )
            tool = build_workout_draft_tools(
                SimpleNamespace(user_id=user.id, workout_service=workouts)
            )[0]
            with pytest.raises(WorkoutConflictError):
                await tool.ainvoke({"workout_id": str(aggregate.workout.id)})
            exercise = aggregate.exercises[0]
            for index in range(1, int(exercise.target_snapshot["sets"]) + 1):
                await workouts.create_set(
                    user.id,
                    aggregate.workout.id,
                    WorkoutSetCreateRequest(
                        client_generated_id=uuid4(),
                        workout_exercise_id=exercise.id,
                        set_index=index,
                        weight_kg=Decimal("50"),
                        reps=5,
                        rir=3,
                        tags=["working"],
                        completed_at=started + timedelta(minutes=index),
                    ),
                )
            await workouts.finish_workout(
                user.id,
                aggregate.workout.id,
                WorkoutFinishRequest(
                    ended_at=started + timedelta(minutes=50),
                    expected_version=aggregate.workout.version,
                    interruption_reason="时间不足" if interrupted else None,
                    pain=[{"area": "膝盖", "severity": 3}] if pain else [],
                ),
            )
            result = await tool.ainvoke({"workout_id": str(aggregate.workout.id)})
            suggestion = result["draft"]["suggestions"][0]
            expected = Decimal("50") if pain or interrupted else Decimal("52.5")
            assert Decimal(suggestion["proposed_target"]["weight_kg"]) == expected
            assert bool(suggestion["warnings"]) == (pain or interrupted)
            assert suggestion["exercise_name"] == exercise.name_snapshot
            pending_event = await session.scalar(
                select(CalendarEvent)
                .where(CalendarEvent.user_id == user.id, CalendarEvent.actual_workout_id.is_(None))
                .order_by(CalendarEvent.scheduled_date)
            )
            compressed = await training.create_compression_draft(
                user.id,
                CompressionDraftCreateRequest(
                    event_id=pending_event.id, target_minutes=15, reason="保持本次短训练安排"
                ),
            )
            compression_card = await training.submit_reschedule(
                user.id, compressed.id, compressed.version
            )
            await approvals.approve(user.id, compression_card.id, compression_card.version)
            original_count = len(pending_event.content_snapshot["exercises"])
            assert (await training_repository.get_active_plan(user.id)).id == original_plan.id
            card = result["confirmation"]
            await approvals.approve(user.id, UUID(card["confirmation_id"]), card["version"])
            updated = await training_repository.get_active_plan(user.id)
            assert updated.version == original_plan.version + 1
            assert pending_event.estimated_minutes == 15
            assert pending_event.content_snapshot["estimated_minutes"] == 15
            assert len(pending_event.content_snapshot["exercises"]) == original_count
            updated_exercise = next(
                item
                for day in updated.days
                for item in day["exercises"]
                if item["exercise_id"] == str(exercise.exercise_id)
            )
            assert Decimal(updated_exercise["target_load_kg"]) == expected
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_workout_date_filter_matches_local_date_at_week_boundary():
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            user = User(username=f"week-boundary-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            service = WorkoutService(
                SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
            )
            # Sunday UTC, already Monday in China. Previous week must exclude it.
            started = datetime(2026, 10, 4, 16, 30, tzinfo=UTC)
            aggregate = await service.create_workout(
                user.id, WorkoutCreateRequest(started_at=started)
            )
            await service.finish_workout(
                user.id,
                aggregate.workout.id,
                WorkoutFinishRequest(
                    ended_at=started + timedelta(minutes=20),
                    expected_version=aggregate.workout.version,
                ),
            )
            previous = await service.list_history(
                user_id=user.id,
                start_date=datetime(2026, 9, 28).date(),
                end_date=datetime(2026, 10, 4).date(),
            )
            current = await service.list_history(
                user_id=user.id,
                start_date=datetime(2026, 10, 5).date(),
                end_date=datetime(2026, 10, 5).date(),
            )
            assert previous.total == 0
            assert current.total == 1
            assert current.list[0].date.isoformat() == "2026-10-05"
            utc = await service.list_history(
                user_id=user.id,
                start_date=datetime(2026, 10, 4).date(),
                end_date=datetime(2026, 10, 4).date(),
                timezone="UTC",
            )
            assert utc.total == 1 and utc.list[0].date.isoformat() == "2026-10-04"
        finally:
            await transaction.rollback()
