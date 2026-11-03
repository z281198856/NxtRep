from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.nutrition import NutritionEntryCopyRequest
from nxtrep_backend.services.nutrition import (
    NutritionConflictError,
    NutritionNotFoundError,
    NutritionService,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "meals,expected",
    [
        ([], []),
        (["breakfast", "breakfast", "snack"], ["breakfast"]),
        (["lunch", "dinner", "other", "snack"], ["lunch", "dinner"]),
        (["breakfast", "lunch", "dinner", "snack"], ["breakfast", "lunch", "dinner"]),
    ],
)
async def test_daily_coverage_counts_distinct_main_meals_only(meals, expected):
    totals = {"kcal": "100", "protein_g": "5", "carbs_g": "10", "fat_g": "4"}
    values = {
        "kcal_min": "1800",
        "kcal_max": "2000",
        "protein_min_g": "100",
        "protein_max_g": "130",
        "carbs_min_g": "200",
        "carbs_max_g": "250",
        "fat_min_g": "50",
        "fat_max_g": "60",
    }
    repo = SimpleNamespace(
        list_entries=AsyncMock(
            return_value=[SimpleNamespace(meal_type=m, totals=totals) for m in meals]
        ),
        get_active_target=AsyncMock(return_value=SimpleNamespace(values=values)),
    )
    result = await NutritionService(repo).daily_summary(uuid4(), date(2026, 10, 23))
    assert result["recorded_meals"] == expected
    assert result["record_completeness"] == (Decimal(len(expected)) / 3).quantize(Decimal(".01"))
    assert result["target"] == values
    assert result["consumed"]["kcal"] == 100 * len(meals)
    assert Decimal(result["remaining"]["kcal_min"]) == 1800 - 100 * len(meals)


@pytest.mark.asyncio
async def test_copy_preserves_snapshot_without_mutating_original_and_checks_owner_version():
    owner, entry_id = uuid4(), uuid4()
    source = SimpleNamespace(
        items=[{"name": "原米饭", "amount_g": "120", "kcal": "150"}],
        totals={"kcal": "150"},
        version=2,
        is_flexible_meal=False,
        notes="原备注",
    )
    repo = SimpleNamespace(
        get_entry=AsyncMock(return_value=source),
        add_entry=AsyncMock(side_effect=lambda entry: entry),
    )
    service = NutritionService(repo)
    body = NutritionEntryCopyRequest(
        expected_version=2, meal_type="breakfast", eaten_at="2026-10-22T08:00:00+08:00"
    )
    copied = await service.copy_entry(owner, entry_id, body)
    repo.get_entry.assert_awaited_once_with(owner, entry_id, lock=True)
    assert copied.user_id == owner and copied.meal_type == "breakfast"
    assert copied.eaten_at == datetime.fromisoformat("2026-10-22T08:00:00+08:00")
    assert copied.items == source.items and copied.totals == source.totals
    copied.items[0]["amount_g"] = "999"
    assert source.items[0]["amount_g"] == "120"
    with pytest.raises(NutritionConflictError):
        await service.copy_entry(owner, entry_id, body.model_copy(update={"expected_version": 1}))
    repo.get_entry.return_value = None
    with pytest.raises(NutritionNotFoundError):
        await service.copy_entry(owner, entry_id, body)
    assert repo.add_entry.await_count == 1


def test_copy_requires_timezone_and_version():
    with pytest.raises(ValidationError):
        NutritionEntryCopyRequest(
            expected_version=1, meal_type="lunch", eaten_at="2026-10-23T12:00:00"
        )
