from datetime import UTC, datetime

import pytest

from nxtrep_backend.services.agent_task_parameters import (
    normalize_task_parameters,
    remaining_draft_fields,
)


@pytest.mark.parametrize(
    "word,expected", [("今天", "2026-10-09"), ("昨天", "2026-10-08"), ("前天", "2026-10-07")]
)
def test_relative_date_uses_user_timezone(word, expected):
    values, missing = normalize_task_parameters(
        {"workout_date": word},
        timezone="Asia/Shanghai",
        occurred_at=datetime(2026, 10, 8, 17, tzinfo=UTC),
    )
    assert values["workout_date"] == expected
    assert missing == []


def test_invalid_parameters_are_missing_instead_of_reused_or_defaulted():
    values, missing = normalize_task_parameters(
        {
            "weight_kg": "-55",
            "sets": 0,
            "reps": "eight",
            "workout_date": "2026-02-30",
            "exercise_name": "卧推",
        }
    )
    assert values == {"exercise_name": "卧推"}
    assert set(missing) == {"weight_kg", "sets", "reps", "workout_date"}


def test_valid_iso_date_and_zero_bodyweight_remain_valid():
    values, missing = normalize_task_parameters({"workout_date": "2026-10-08", "weight_kg": 0})
    assert values["workout_date"] == "2026-10-08"
    assert values["weight_kg"] == "0"
    assert missing == []


@pytest.mark.parametrize(
    "field",
    ["amount_g", "items[].amount_g", "items[0].amount_g", "items[].nutrients", "kcal"],
)
def test_new_meal_named_food_allows_estimable_fields(field):
    assert (
        remaining_draft_fields(
            "nutrition_record_draft",
            [field],
            {"items": [{"food_name": "米饭", "amount_g": "一盒"}]},
            {},
        )
        == []
    )


def test_unknown_food_and_genuine_selection_or_safety_fields_are_not_estimable():
    fields = ["food_name", "amount_g", "selection", "injury_clearance"]
    assert remaining_draft_fields("nutrition_record_draft", fields, {}, {}) == fields
    assert remaining_draft_fields("nutrition_record_draft", fields, {"food_name": "米饭"}, {}) == [
        "selection",
        "injury_clearance",
    ]


@pytest.mark.parametrize("entity", ["entry_id", "meal_id", "confirmation_id", "food_id"])
def test_existing_business_entity_does_not_allow_default_quantity_correction(entity):
    assert remaining_draft_fields(
        "nutrition_record_draft", ["amount_g"], {"food_name": "米饭"}, {entity: "known-id"}
    ) == ["amount_g"]


@pytest.mark.parametrize(
    "actions,expected",
    [
        (["create"], []),
        (["update"], ["basis_amount_g", "nutrients"]),
        (["delete"], ["basis_amount_g", "nutrients"]),
        (["create", "update"], ["basis_amount_g", "nutrients"]),
        ([], ["basis_amount_g", "nutrients"]),
    ],
)
def test_only_explicit_food_catalog_creation_allows_estimates(actions, expected):
    assert (
        remaining_draft_fields(
            "food_catalog_draft",
            ["basis_amount_g", "nutrients"],
            {"food_name": "葱烧豆腐"},
            {},
            food_catalog_actions=actions,
        )
        == expected
    )


@pytest.mark.parametrize("amount", [-1, 0, "NaN", "Infinity", True, False])
def test_nested_explicit_invalid_numbers_remain_missing(amount):
    assert "items[0].amount_g" in remaining_draft_fields(
        "nutrition_record_draft",
        ["items[].amount_g"],
        {"items": [{"food_name": "米饭", "amount_g": amount}]},
        {},
    )


@pytest.mark.parametrize("amount", [-1, 0, "NaN", "Infinity", True, False])
def test_top_level_invalid_quantity_cannot_be_erased_as_optional(amount):
    values, invalid = normalize_task_parameters({"food_name": "米饭", "amount_g": amount})
    assert "amount_g" in invalid
    assert remaining_draft_fields(
        "nutrition_record_draft", ["amount_g"], values, {}, invalid_fields=invalid
    ) == ["amount_g"]


def test_many_invalid_portions_do_not_overflow_persisted_state():
    from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState
    from nxtrep_backend.services.agent_task_state import TaskStateManager

    fields = remaining_draft_fields(
        "nutrition_record_draft",
        ["selection"],
        {"items": [{"food_name": f"食物{i}", "amount_g": -1} for i in range(20)]},
        {},
    )
    assert len(fields) <= 20 and "selection" in fields
    state = AgentTaskState(
        active_task=AgentTask(task_type="nutrition_record_draft", missing_fields=fields)
    )
    assert TaskStateManager.load(state.model_dump(mode="json")).active_task is not None
