from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.db.base import Base
from nxtrep_backend.main import app
from nxtrep_backend.schemas.nutrition import (
    DynamicNutritionTargetDraftRequest,
    NutritionEntryDraftUpdateRequest,
    RecipeUpdateRequest,
)
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionService


def test_extended_backend_routes_are_exposed() -> None:
    schema = app.openapi()
    expected = {
        "/api/v1/exercise-content/{exercise_id}/feedback": "post",
        "/api/v1/training/plan-drafts:parse-image": "post",
        "/api/v1/calendar/compression-drafts": "post",
        "/api/v1/calendar/substitution-drafts": "post",
        "/api/v1/workouts/{workout_id}/revisions": "get",
        "/api/v1/foods/barcodes/{code}": "get",
        "/api/v1/nutrition/dynamic-target-drafts": "post",
        "/api/v1/recipes": "post",
        "/api/v1/recipes/{recipe_id}": "patch",
        "/api/v1/body/photos/uploads": "post",
        "/api/v1/body/photos/{photo_id}/analysis-drafts": "post",
        "/api/v1/body/photos/compare": "post",
        "/api/v1/progress/muscle-volume": "get",
        "/api/v1/progress/recovery": "get",
        "/api/v1/progress/correlations": "get",
        "/api/v1/reports/monthly": "post",
        "/api/v1/reports/phase": "post",
        "/api/v1/alerts": "get",
        "/api/v1/admin/knowledge/sources": "post",
        "/api/v1/admin/knowledge/search": "post",
        "/api/v1/admin/jobs": "get",
        "/api/v1/agent/conversations": "post",
        "/api/v1/agent/conversations/{conversation_id}/messages": "post",
    }
    for path, method in expected.items():
        assert method in schema["paths"][path], path


def test_extended_tables_are_registered() -> None:
    assert {"recipes", "exercise_content_feedback", "alerts"} <= set(Base.metadata.tables)
    assert "barcode" in Base.metadata.tables["foods"].c


def test_recipe_update_requires_a_real_change() -> None:
    with pytest.raises(ValidationError):
        RecipeUpdateRequest(expected_version=1)
    with pytest.raises(ValidationError):
        RecipeUpdateRequest(expected_version=1, name=None)


def test_nutrition_draft_update_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        NutritionEntryDraftUpdateRequest(
            expected_version=1,
            eaten_at=datetime(2026, 9, 12, 12, 0),
        )


class _DynamicTargetRepository:
    def __init__(self, recorded_days: int) -> None:
        start = datetime(2026, 8, 29, 12, tzinfo=UTC)
        self.entries = [
            SimpleNamespace(eaten_at=start + timedelta(days=index))
            for index in range(recorded_days)
        ]
        self.target = SimpleNamespace(
            values={
                "kcal_min": "2000",
                "kcal_max": "2200",
                "protein_min_g": "120",
                "protein_max_g": "140",
                "carbs_min_g": "200",
                "carbs_max_g": "240",
                "fat_min_g": "50",
                "fat_max_g": "70",
            }
        )
        self.saved = None

    async def list_entries_range(self, *_args):
        return self.entries

    async def get_active_target(self, *_args):
        return self.target

    async def add_target_draft(self, draft):
        self.saved = draft
        return draft


@pytest.mark.asyncio
async def test_dynamic_target_scales_current_ranges_after_fourteen_days() -> None:
    repository = _DynamicTargetRepository(14)
    result = await NutritionService(repository).create_dynamic_target_draft(
        uuid4(),
        DynamicNutritionTargetDraftRequest(
            effective_from=date(2026, 9, 12),
            desired_direction="decrease",
        ),
    )
    assert result.kcal_min == Decimal("1900.00")
    assert result.protein_max_g == Decimal("133.00")


@pytest.mark.asyncio
async def test_dynamic_target_requires_fourteen_recorded_days() -> None:
    with pytest.raises(NutritionConflictError):
        await NutritionService(_DynamicTargetRepository(13)).create_dynamic_target_draft(
            uuid4(),
            DynamicNutritionTargetDraftRequest(
                effective_from=date(2026, 9, 12),
                desired_direction="maintain",
            ),
        )


class _MuscleVolumeRepository:
    async def muscle_volume_rows(self, *_args):
        return [
            ("chest", "primary", Decimal("100"), 10),
            ("triceps", "secondary", Decimal("100"), 10),
        ]


@pytest.mark.asyncio
async def test_secondary_muscle_volume_is_weighted_at_half() -> None:
    data = await BodyService(_MuscleVolumeRepository()).muscle_volume(
        uuid4(), date(2026, 9, 1), date(2026, 9, 12)
    )
    assert data["distribution"] == [
        {"muscle": "chest", "volume_kg": "1000.00", "set_count": 1},
        {"muscle": "triceps", "volume_kg": "500.00", "set_count": 1},
    ]
