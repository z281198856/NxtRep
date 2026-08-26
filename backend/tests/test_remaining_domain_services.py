from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import (
    Confirmation,
    Food,
    FoodVersion,
    NutritionEntry,
    TrainingPlanDraft,
)
from nxtrep_backend.schemas.body import NavyBodyFatRequest
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest, NutritionItemInput
from nxtrep_backend.schemas.training import PlanDraftCreateRequest
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.training import TrainingService


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

    async def get_food_version(self, version_id):
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
