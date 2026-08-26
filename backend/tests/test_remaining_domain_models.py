from sqlalchemy.dialects.postgresql import JSONB

from nxtrep_backend.db.base import Base
from nxtrep_backend.db.models import (  # noqa: F401
    BodyFatEstimate,
    BodyMeasurement,
    CalendarEvent,
    CalendarRescheduleDraft,
    Confirmation,
    Food,
    FoodVersion,
    NutritionEntry,
    NutritionTargetDraft,
    NutritionTargetVersion,
    PersonalRecord,
    ProgressionDraft,
    TrainingPlanDraft,
    TrainingPlanVersion,
    TrainingTemplate,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)

EXPECTED_TABLES = {
    "training_templates",
    "training_plan_drafts",
    "training_plan_versions",
    "calendar_events",
    "calendar_reschedule_drafts",
    "workouts",
    "workout_exercises",
    "workout_sets",
    "workout_set_revisions",
    "progression_drafts",
    "personal_records",
    "foods",
    "food_versions",
    "nutrition_entries",
    "nutrition_entry_revisions",
    "nutrition_target_drafts",
    "nutrition_target_versions",
    "body_measurements",
    "body_measurement_revisions",
    "body_fat_estimates",
    "confirmations",
}


def test_all_remaining_domain_tables_are_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_snapshot_columns_use_postgresql_jsonb() -> None:
    expected = {
        ("training_templates", "days"),
        ("training_plan_drafts", "days"),
        ("training_plan_versions", "days"),
        ("workout_exercises", "target_snapshot"),
        ("nutrition_entries", "items"),
        ("nutrition_entries", "totals"),
        ("confirmations", "after"),
    }
    for table_name, column_name in expected:
        assert isinstance(Base.metadata.tables[table_name].c[column_name].type, JSONB)


def test_history_tables_reference_their_current_record() -> None:
    expected = {
        "workout_set_revisions": "workout_sets.id",
        "nutrition_entry_revisions": "nutrition_entries.id",
        "body_measurement_revisions": "body_measurements.id",
    }
    for table_name, target in expected.items():
        foreign_keys = {fk.target_fullname for fk in Base.metadata.tables[table_name].foreign_keys}
        assert target in foreign_keys


def test_plan_and_target_have_single_active_partial_indexes() -> None:
    for table_name in ("training_plan_versions", "nutrition_target_versions"):
        indexes = {index.name: index for index in Base.metadata.tables[table_name].indexes}
        active = next(index for name, index in indexes.items() if "one_active_user" in name)
        assert active.unique is True
        assert active.dialect_options["postgresql"]["where"] is not None
