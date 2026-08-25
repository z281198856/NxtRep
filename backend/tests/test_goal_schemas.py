from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.goals import GoalsAndConstraintsUpdateRequest


def make_request(**changes: object) -> GoalsAndConstraintsUpdateRequest:
    data: dict[str, object] = {
        "goal_type": "muscle_gain",
        "equipment": ["barbell", "dumbbell"],
    }
    data.update(changes)
    return GoalsAndConstraintsUpdateRequest.model_validate(data)


def test_goals_request_accepts_and_normalizes_valid_data() -> None:
    request = make_request(
        target_weight_kg="72.500",
        equipment=[" BARBELL ", "dumbbell"],
        pain_or_injuries=[
            {
                "kind": "current_pain",
                "body_part": " left knee ",
                "severity": 3,
                "notes": "  Avoid deep flexion  ",
            }
        ],
    )

    assert request.target_weight_kg == Decimal("72.500")
    assert request.equipment == ["barbell", "dumbbell"]
    assert request.pain_or_injuries[0].body_part == "left knee"
    assert request.pain_or_injuries[0].notes == "Avoid deep flexion"


def test_goals_request_requires_equipment_field_but_allows_empty_list() -> None:
    with pytest.raises(ValidationError):
        GoalsAndConstraintsUpdateRequest.model_validate({"goal_type": "strength"})

    assert make_request(equipment=[]).equipment == []


def test_goals_request_rejects_past_target_date() -> None:
    with pytest.raises(ValidationError):
        make_request(target_date=date.today() - timedelta(days=1))


def test_goals_request_rejects_invalid_weight() -> None:
    with pytest.raises(ValidationError):
        make_request(target_weight_kg="500.001")


def test_goals_request_rejects_duplicate_list_items_case_insensitively() -> None:
    with pytest.raises(ValidationError):
        make_request(allergies=["Peanut", "peanut"])


def test_goals_request_rejects_conflicting_exercise_preferences() -> None:
    exercise_id = uuid4()

    with pytest.raises(ValidationError):
        make_request(
            preferred_exercises=[exercise_id],
            disliked_exercises=[exercise_id],
        )


def test_goals_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_request(unknown_field="value")
