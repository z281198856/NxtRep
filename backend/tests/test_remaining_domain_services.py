from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import (
    Confirmation,
    Food,
    FoodVersion,
    NutritionEntry,
    TrainingPlanDraft,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)
from nxtrep_backend.repositories.workout import WorkoutAggregate
from nxtrep_backend.schemas.body import NavyBodyFatRequest
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest, NutritionItemInput
from nxtrep_backend.schemas.training import PlanDraftCreateRequest
from nxtrep_backend.schemas.workout import ProgressionDraftCreateRequest
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.training import TrainingService
from nxtrep_backend.services.workout import WorkoutService


class DummySession:
    async def flush(self) -> None:
        return None


class FakeBodyRepository:
    def __init__(self) -> None:
        self.saved = []

    async def add_body_fat(self, item) -> None:
        self.saved.append(item)


@pytest.mark.asyncio
async def test_navy_body_fat_calculates_range_and_saves_on_request() -> None:
    repository = FakeBodyRepository()
    result = await BodyService(repository).navy_body_fat(
        uuid4(),
        NavyBodyFatRequest(
            sex="male",
            height_cm=Decimal("178"),
            waist_cm=Decimal("82"),
            neck_cm=Decimal("38"),
            save=True,
        ),
    )
    assert Decimal("2") <= result["value_percent"] <= Decimal("70")
    assert result["range_min_percent"] == max(Decimal("0"), result["value_percent"] - Decimal("3"))
    assert len(repository.saved) == 1
    assert repository.saved[0].method == "navy"


class FakeTrainingRepository:
    def __init__(self, visible_ids: set) -> None:
        self.session = DummySession()
        self.visible_ids = visible_ids
        self.added = []

    async def add_draft(self, draft):
        draft.id = uuid4()
        self.added.append(draft)
        return draft

    async def visible_exercise_ids(self, user_id, exercise_ids):
        return exercise_ids & self.visible_ids


@pytest.mark.asyncio
async def test_manual_plan_assigns_snapshot_ids_and_validates_exercises() -> None:
    exercise_id = uuid4()
    repository = FakeTrainingRepository({exercise_id})
    body = PlanDraftCreateRequest.model_validate(
        {
            "name": "全身训练",
            "weekly_frequency": 1,
            "days": [
                {
                    "day_index": 1,
                    "name": "训练A",
                    "estimated_minutes": 60,
                    "exercises": [
                        {
                            "exercise_id": str(exercise_id),
                            "order_no": 1,
                            "target_sets": 3,
                            "rep_min": 8,
                            "rep_max": 12,
                        }
                    ],
                }
            ],
        }
    )
    draft = await TrainingService(repository).create_manual_draft(uuid4(), body)
    assert draft.validation_errors == []
    assert draft.days[0]["id"]
    assert draft.days[0]["exercises"][0]["id"]


@pytest.mark.asyncio
async def test_plan_validation_reports_unavailable_exercise() -> None:
    missing_id = uuid4()
    repository = FakeTrainingRepository(set())
    draft = TrainingPlanDraft(
        id=uuid4(),
        user_id=uuid4(),
        name="计划",
        weekly_frequency=1,
        days=[
            {
                "id": str(uuid4()),
                "day_index": 1,
                "name": "A",
                "estimated_minutes": 30,
                "exercises": [{"exercise_id": str(missing_id)}],
            }
        ],
        source="manual",
        status="editing",
        validation_errors=[],
        validation_warnings=[],
        version=1,
    )
    errors, _, _ = await TrainingService(repository).validate_draft(draft.user_id, draft)
    assert any(str(missing_id) in item["message"] for item in errors)


class FakeNutritionRepository:
    def __init__(self, food, version) -> None:
        self.food = food
        self.version = version
        self.entry = None

    async def get_food_version(self, user_id, version_id):
        return (self.food, self.version) if version_id == self.version.id else None

    async def add_entry(self, entry):
        entry.id = uuid4()
        self.entry = entry
        return entry


@pytest.mark.asyncio
async def test_nutrition_entry_scales_snapshot_nutrients_by_amount() -> None:
    food = Food(id=uuid4(), name="熟鸡胸肉")
    version = FoodVersion(
        id=uuid4(),
        food_id=food.id,
        version=1,
        basis_amount_g=Decimal("100"),
        kcal=Decimal("165"),
        protein_g=Decimal("31"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("3.6"),
        source="USDA",
        confidence="high",
    )
    repository = FakeNutritionRepository(food, version)
    body = NutritionEntryCreateRequest(
        meal_type="lunch",
        eaten_at=datetime.now(UTC),
        items=[NutritionItemInput(food_version_id=version.id, amount_g=Decimal("200"))],
    )
    entry: NutritionEntry = await NutritionService(repository).create_entry(uuid4(), body)
    assert Decimal(entry.totals["kcal"]) == Decimal("330")
    assert Decimal(entry.totals["protein_g"]) == Decimal("62")
    assert entry.items[0]["name"] == "熟鸡胸肉"


class FakeDailySummaryRepository:
    async def list_entries(self, user_id, day):
        return [
            SimpleNamespace(
                totals={
                    "kcal": "1650",
                    "protein_g": "112",
                    "carbs_g": "170",
                    "fat_g": "55",
                }
            )
        ]

    async def get_active_target(self, user_id, day):
        return SimpleNamespace(
            values={
                "kcal_min": "2200",
                "kcal_max": "2400",
                "protein_min_g": "140",
                "protein_max_g": "160",
                "carbs_min_g": "220",
                "carbs_max_g": "280",
                "fat_min_g": "55",
                "fat_max_g": "75",
            }
        )


@pytest.mark.asyncio
async def test_daily_summary_returns_remaining_for_all_macronutrients() -> None:
    result = await NutritionService(FakeDailySummaryRepository()).daily_summary(
        uuid4(), date.today()
    )
    assert result["remaining"] == {
        "kcal_min": "550",
        "kcal_max": "750",
        "protein_min_g": "28",
        "protein_max_g": "48",
        "carbs_min_g": "50",
        "carbs_max_g": "110",
        "fat_min_g": "0",
        "fat_max_g": "20",
    }


class FakeProgressionRepository:
    def __init__(self, aggregate: WorkoutAggregate) -> None:
        self.aggregate = aggregate

    async def get_aggregate(self, user_id, workout_id):
        return self.aggregate

    async def add_progression_draft(self, draft):
        draft.id = uuid4()
        return draft


@pytest.mark.asyncio
async def test_progression_does_not_increase_load_when_pain_is_recorded() -> None:
    user_id = uuid4()
    workout = Workout(
        id=uuid4(),
        user_id=user_id,
        status="completed",
        started_at=datetime.now(UTC),
        pain=[{"body_part": "knee", "severity": 3}],
        version=2,
    )
    exercise = WorkoutExercise(
        id=uuid4(),
        workout_id=workout.id,
        exercise_id=uuid4(),
        original_exercise_id=uuid4(),
        name_snapshot="深蹲",
        target_snapshot={"sets": 1, "rep_min": 5, "rep_max": 5},
        order_no=1,
    )
    recorded_set = WorkoutSet(
        id=uuid4(),
        workout_id=workout.id,
        workout_exercise_id=exercise.id,
        client_generated_id=uuid4(),
        set_index=1,
        weight_kg=Decimal("100"),
        reps=5,
        rir=3,
        tags=["working"],
        completed_at=datetime.now(UTC),
        version=1,
    )
    aggregate = WorkoutAggregate(workout, [exercise], {exercise.id: [recorded_set]})
    draft = await WorkoutService(
        FakeProgressionRepository(aggregate), SimpleNamespace()
    ).create_progression_draft(user_id, workout.id, ProgressionDraftCreateRequest())
    suggestion = draft.suggestions[0]
    assert suggestion["proposed_target"]["weight_kg"] == "100"
    assert any("疼痛" in warning for warning in suggestion["warnings"])


class FakeProgressOverviewRepository:
    async def progress_rows(self, user_id, start_date, end_date):
        start = datetime(2026, 8, 25, 10, tzinfo=UTC)
        workouts = [
            SimpleNamespace(
                status="completed",
                started_at=start,
                ended_at=start + timedelta(hours=1),
            )
        ]
        entries = [
            SimpleNamespace(eaten_at=start, totals={"kcal": "1000"}),
            SimpleNamespace(eaten_at=start + timedelta(hours=2), totals={"kcal": "500"}),
            SimpleNamespace(eaten_at=start + timedelta(days=1), totals={"kcal": "2000"}),
        ]
        measurements = [
            SimpleNamespace(weight_kg=Decimal("75")),
            SimpleNamespace(weight_kg=Decimal("74")),
        ]
        calendar_events = [
            SimpleNamespace(scheduled_date=date(2026, 8, 25), status="completed"),
            SimpleNamespace(scheduled_date=date(2026, 8, 26), status="missed"),
        ]
        return workouts, entries, measurements, [], calendar_events


@pytest.mark.asyncio
async def test_progress_overview_uses_daily_nutrition_and_calendar_completion() -> None:
    result = await BodyService(FakeProgressOverviewRepository()).overview(
        uuid4(), date(2026, 8, 25), date(2026, 8, 26)
    )
    assert result["training"]["completion_rate"] == "0.50"
    assert result["nutrition"]["average_kcal"] == "1750.00"
    assert result["nutrition"]["record_completeness"] == "1.00"
    assert result["body"]["smoothed_change_kg"] == "-1.00"


class FakeConfirmationRepository:
    def __init__(self, item: Confirmation) -> None:
        self.item = item
        self.session = DummySession()

    async def get_confirmation(self, user_id, confirmation_id, *, lock=False):
        if self.item.user_id == user_id and self.item.id == confirmation_id:
            return self.item
        return None


@pytest.mark.asyncio
async def test_rejecting_confirmation_does_not_execute_business_operation() -> None:
    user_id = uuid4()
    item = Confirmation(
        id=uuid4(),
        user_id=user_id,
        operation_type="training_plan_activate",
        before=None,
        after={"plan_draft_id": str(uuid4())},
        reason="test",
        impact="none",
        status="pending",
        version=1,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    result = await DatabaseConfirmationService(FakeConfirmationRepository(item)).reject(
        user_id, item.id, 1, "暂不修改"
    )
    assert result.status == "rejected"
    assert result.result is None
    assert result.rejection_reason == "暂不修改"
    assert result.version == 2
