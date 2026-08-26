from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest, NavyBodyFatRequest
from nxtrep_backend.schemas.nutrition import NutritionItemInput, NutritionTargetDraftRequest
from nxtrep_backend.schemas.training import (
    PlanDraftCreateRequest,
    RescheduleDraftCreateRequest,
)
from nxtrep_backend.schemas.workout import WorkoutSetCreateRequest


def valid_plan_payload() -> dict:
    return {
        "name": "三天全身训练",
        "weekly_frequency": 1,
        "days": [
            {
                "day_index": 1,
                "name": "训练A",
                "estimated_minutes": 60,
                "exercises": [
                    {
                        "exercise_id": str(uuid4()),
                        "order_no": 1,
                        "target_sets": 5,
                        "rep_min": 5,
                        "rep_max": 5,
                    }
                ],
            }
        ],
    }


def test_plan_requires_frequency_to_match_day_count() -> None:
    payload = valid_plan_payload()
    payload["weekly_frequency"] = 2
    with pytest.raises(ValidationError, match="weekly_frequency"):
        PlanDraftCreateRequest.model_validate(payload)


def test_plan_rejects_reversed_rep_range() -> None:
    payload = valid_plan_payload()
    payload["days"][0]["exercises"][0]["rep_min"] = 10
    payload["days"][0]["exercises"][0]["rep_max"] = 5
    with pytest.raises(ValidationError, match="rep_min"):
        PlanDraftCreateRequest.model_validate(payload)


def test_shift_reschedule_requires_target_date() -> None:
    with pytest.raises(ValidationError, match="target_date"):
        RescheduleDraftCreateRequest(missed_event_id=uuid4(), strategy="shift")


def test_custom_nutrition_estimate_requires_complete_snapshot() -> None:
    with pytest.raises(ValidationError, match="custom estimates"):
        NutritionItemInput(amount_g=Decimal("100"), name="估算食物")


def test_nutrition_target_rejects_reversed_ranges() -> None:
    with pytest.raises(ValidationError, match="minimum"):
        NutritionTargetDraftRequest(
            effective_from=date.today(),
            kcal_min=2400,
            kcal_max=2200,
            protein_min_g=140,
            protein_max_g=160,
            carbs_min_g=220,
            carbs_max_g=280,
            fat_min_g=55,
            fat_max_g=75,
        )


def test_body_measurement_requires_at_least_one_value() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        BodyMeasurementCreateRequest(measured_at=datetime.now(UTC), source="manual")


def test_female_navy_formula_requires_hip_measurement() -> None:
    with pytest.raises(ValidationError, match="hip_cm"):
        NavyBodyFatRequest(sex="female", height_cm=165, waist_cm=70, neck_cm=32)


def test_workout_set_enforces_rir_range_and_tag_vocabulary() -> None:
    with pytest.raises(ValidationError):
        WorkoutSetCreateRequest(
            client_generated_id=uuid4(),
            workout_exercise_id=uuid4(),
            set_index=1,
            weight_kg="60.000",
            reps=5,
            rir=11,
            tags=["invalid"],
            completed_at=datetime.now(UTC),
        )
