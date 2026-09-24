from importlib.util import module_from_spec, spec_from_file_location
from itertools import product
from pathlib import Path
from uuid import UUID

from nxtrep_backend.schemas.training import PlanDraftCreateRequest


def load_catalog():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "b3c4d5e6f7a8_expand_training_templates.py"
    )
    spec = spec_from_file_location("training_catalog_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_frontend_selection_has_a_compatible_template():
    rows = load_catalog().template_rows()
    goals = ("muscle_gain", "fat_loss_retain", "recomposition", "maintain", "strength")
    for goal, frequency, equipment in product(
        goals, range(1, 8), ("bodyweight", "dumbbell", "barbell", "cable")
    ):
        assert any(
            goal in row["goal_types"]
            and row["days_per_week"] == frequency
            and equipment in row["equipment"]
            and set(row["equipment"]) <= {equipment, "bodyweight"}
            for row in rows
        ), (goal, frequency, equipment)


def test_templates_use_valid_unique_snapshots_and_real_exercise_ids():
    catalog = load_catalog()
    rows = catalog.template_rows()
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["name"] for row in rows}) == len(rows)
    snapshot_ids = []
    for row in rows:
        days = []
        for day in row["days"]:
            snapshot_ids.append(day["id"])
            for item in day["exercises"]:
                UUID(item["exercise_id"])
                snapshot_ids.append(item["id"])
            days.append(
                {
                    **{k: v for k, v in day.items() if k not in {"id", "exercises"}},
                    "exercises": [
                        {k: v for k, v in item.items() if k != "id"} for item in day["exercises"]
                    ],
                }
            )
        PlanDraftCreateRequest(name=row["name"], weekly_frequency=row["days_per_week"], days=days)
        assert all(day["exercises"] for day in days)
    assert len(set(snapshot_ids)) == len(snapshot_ids)
    assert rows == catalog.template_rows()


def test_high_frequency_plans_include_recovery_and_low_frequency_plans_space_sessions():
    for row in load_catalog().template_rows():
        if row["days_per_week"] == 3:
            assert [day["day_index"] for day in row["days"]] == [1, 3, 5]
        if row["days_per_week"] >= 5:
            recovery = [day for day in row["days"] if "轻量恢复" in day["name"]]
            assert len(recovery) == row["days_per_week"] - 4
            assert all(
                item["target_sets"] == 1 and item["target_rir"] >= 5
                for day in recovery
                for item in day["exercises"]
            )


def test_strength_accessories_do_not_use_low_rep_heavy_prescriptions():
    catalog = load_catalog()
    compound_ids = {str(catalog.exercise_id(slug)) for slug in catalog.HEAVY_COMPOUNDS}
    for row in catalog.template_rows():
        if row["goal_types"] != ["strength"]:
            continue
        for day in row["days"]:
            for item in day["exercises"]:
                if item["exercise_id"] not in compound_ids:
                    assert item["rep_min"] >= 8
                assert item["target_load_kg"] is None
