from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import (
    SqlAlchemyConfirmationRepository,
)
from nxtrep_backend.repositories.memory import SqlAlchemyMemoryRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionItemInput,
)
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.memory import MemoryService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.training import TrainingService


def make_confirmation_repository() -> MagicMock:
    repository = MagicMock(spec=SqlAlchemyConfirmationRepository)
    repository.add_confirmation = AsyncMock(side_effect=lambda item: item)
    return repository


@pytest.mark.asyncio
async def test_nutrition_entry_proposal_does_not_write_entry() -> None:
    nutrition_repository = MagicMock(spec=SqlAlchemyNutritionRepository)
    nutrition_repository.add_entry = AsyncMock()
    confirmations = make_confirmation_repository()
    service = NutritionService(nutrition_repository, confirmations)
    body = NutritionEntryCreateRequest(
        meal_type="lunch",
        eaten_at=datetime(2026, 9, 3, 12, tzinfo=UTC),
        items=[
            NutritionItemInput(
                amount_g=150,
                name="米饭",
                basis_amount_g=100,
                kcal=116,
                protein_g=2.6,
                carbs_g=25.9,
                fat_g=0.3,
                source="vision_estimate",
                confidence="medium",
            )
        ],
    )

    confirmation = await service.propose_entry(user_id=uuid4(), body=body)

    assert confirmation.operation_type == "nutrition_entry_create"
    assert confirmation.after["entry"]["meal_type"] == "lunch"
    nutrition_repository.add_entry.assert_not_awaited()
    confirmations.add_confirmation.assert_awaited_once()


@pytest.mark.asyncio
async def test_body_measurement_proposal_does_not_write_measurement() -> None:
    body_repository = MagicMock(spec=SqlAlchemyBodyRepository)
    body_repository.add_measurement = AsyncMock()
    confirmations = make_confirmation_repository()
    service = BodyService(body_repository, confirmations)
    body = BodyMeasurementCreateRequest(
        measured_at=datetime(2026, 9, 3, 8, tzinfo=UTC),
        weight_kg=70.5,
        source="manual",
    )

    confirmation = await service.propose_measurement(
        user_id=uuid4(),
        body=body,
    )

    assert confirmation.operation_type == "body_measurement_create"
    assert confirmation.after["measurement"]["weight_kg"] == "70.5"
    body_repository.add_measurement.assert_not_awaited()
    confirmations.add_confirmation.assert_awaited_once()


@pytest.mark.asyncio
async def test_training_service_read_methods_delegate_to_repository() -> None:
    repository = MagicMock(spec=SqlAlchemyTrainingRepository)
    repository.get_active_plan = AsyncMock(return_value=MagicMock())
    repository.list_calendar = AsyncMock(return_value=[])
    service = TrainingService(repository)
    user_id = uuid4()

    await service.get_active_plan(user_id=user_id)
    await service.list_calendar(
        user_id=user_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 7),
    )

    repository.get_active_plan.assert_awaited_once_with(user_id)
    repository.list_calendar.assert_awaited_once_with(
        user_id,
        date(2026, 9, 1),
        date(2026, 9, 7),
    )


@pytest.mark.asyncio
async def test_confirmation_service_get_is_user_scoped() -> None:
    repository = MagicMock(spec=SqlAlchemyConfirmationRepository)
    item = MagicMock(spec=Confirmation)
    repository.get_confirmation = AsyncMock(return_value=item)
    service = DatabaseConfirmationService(repository)
    user_id = uuid4()
    confirmation_id = uuid4()

    result = await service.get(
        user_id=user_id,
        confirmation_id=confirmation_id,
    )

    assert result is item
    repository.get_confirmation.assert_awaited_once_with(
        user_id,
        confirmation_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_type", "after", "service_class", "method_name"),
    [
        (
            "nutrition_entry_create",
            {
                "entry": {
                    "meal_type": "snack",
                    "eaten_at": "2026-09-03T12:00:00Z",
                    "items": [
                        {
                            "amount_g": "100",
                            "name": "苹果",
                            "basis_amount_g": "100",
                            "kcal": "52",
                            "protein_g": "0.3",
                            "carbs_g": "14",
                            "fat_g": "0.2",
                            "source": "estimate",
                            "confidence": "medium",
                        }
                    ],
                    "is_flexible_meal": False,
                    "notes": None,
                }
            },
            NutritionService,
            "create_entry",
        ),
        (
            "body_measurement_create",
            {
                "measurement": {
                    "measured_at": "2026-09-03T08:00:00Z",
                    "weight_kg": "70.5",
                    "waist_cm": None,
                    "neck_cm": None,
                    "hip_cm": None,
                    "body_fat_percent": None,
                    "body_fat_method": None,
                    "source": "manual",
                    "conditions": None,
                    "notes": None,
                }
            },
            BodyService,
            "create_measurement",
        ),
        (
            "memory_create",
            {
                "category": "equipment",
                "content": "家里只有一对可调哑铃",
            },
            MemoryService,
            "create",
        ),
    ],
)
async def test_confirmation_dispatcher_executes_new_proposal_operations(
    monkeypatch,
    operation_type,
    after,
    service_class,
    method_name,
) -> None:
    created = SimpleNamespace(id=uuid4(), version=1)
    method = AsyncMock(return_value=created)
    monkeypatch.setattr(service_class, method_name, method)
    repository = MagicMock(spec=SqlAlchemyConfirmationRepository)
    repository.session = MagicMock()
    service = DatabaseConfirmationService(repository)
    item = SimpleNamespace(
        user_id=uuid4(),
        operation_type=operation_type,
        after=after,
    )

    result = await service._execute(item)

    assert result == {
        "resource_id": str(created.id),
        "resource_version": 1,
    }
    method.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_create_writes_directly() -> None:
    memory_repository = MagicMock(spec=SqlAlchemyMemoryRepository)
    memory_repository.find_exact = AsyncMock(return_value=None)
    memory_repository.add = AsyncMock(side_effect=lambda item: item)
    service = MemoryService(memory_repository)
    user_id = uuid4()

    memory = await service.create(
        user_id=user_id,
        category="equipment",
        content="  家里只有一对可调哑铃  ",
    )

    assert memory.user_id == user_id
    assert memory.category == "equipment"
    assert memory.content == "家里只有一对可调哑铃"
    assert memory.source == "agent_direct"
    memory_repository.add.assert_awaited_once_with(memory)


@pytest.mark.asyncio
async def test_memory_create_reuses_exact_active_duplicate() -> None:
    memory_repository = MagicMock(spec=SqlAlchemyMemoryRepository)
    existing = SimpleNamespace(id=uuid4(), version=1)
    memory_repository.find_exact = AsyncMock(return_value=existing)
    memory_repository.add = AsyncMock()
    service = MemoryService(memory_repository)
    user_id = uuid4()

    result = await service.create(
        user_id=user_id,
        category="equipment",
        content="只有哑铃",
    )

    assert result is existing
    memory_repository.find_exact.assert_awaited_once_with(
        user_id=user_id,
        category="equipment",
        content="只有哑铃",
    )
    memory_repository.add.assert_not_awaited()
