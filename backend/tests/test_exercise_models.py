from uuid import uuid4

from sqlalchemy.dialects.postgresql import JSONB

from nxtrep_backend.db.models.exercise import (
    Exercise,
    ExerciseAlias,
    ExerciseMedia,
    ExerciseMuscle,
    ExerciseSubstitution,
)


def test_exercise_distinguishes_official_and_custom_records() -> None:
    official_exercise = Exercise(
        name_zh="杠铃深蹲",
        equipment="barbell",
    )
    custom_exercise = Exercise(
        owner_user_id=uuid4(),
        name_zh="自定义深蹲",
        equipment="dumbbell",
    )

    assert official_exercise.is_custom is False
    assert custom_exercise.is_custom is True


def test_exercise_content_lists_use_non_nullable_jsonb_columns() -> None:
    table = Exercise.__table__
    jsonb_columns = {
        "instructions",
        "breathing",
        "common_errors",
        "safety_notes",
    }

    for column_name in jsonb_columns:
        column = table.c[column_name]

        assert isinstance(column.type, JSONB)
        assert column.nullable is False
        assert str(column.server_default.arg) == "'[]'::jsonb"


def test_custom_exercise_owner_is_removed_with_user() -> None:
    owner_foreign_key = next(iter(Exercise.__table__.c.owner_user_id.foreign_keys))

    assert owner_foreign_key.target_fullname == "users.id"
    assert owner_foreign_key.ondelete == "CASCADE"


def test_exercise_muscle_uses_composite_primary_key() -> None:
    primary_key_columns = {column.name for column in ExerciseMuscle.__table__.primary_key.columns}

    assert primary_key_columns == {"exercise_id", "muscle_code"}


def test_exercise_muscle_has_cascade_foreign_key_and_search_index() -> None:
    table = ExerciseMuscle.__table__
    exercise_foreign_key = next(iter(table.c.exercise_id.foreign_keys))
    indexed_column_sets = {
        tuple(column.name for column in index.columns) for index in table.indexes
    }

    assert exercise_foreign_key.target_fullname == "exercises.id"
    assert exercise_foreign_key.ondelete == "CASCADE"
    assert ("muscle_code", "role") in indexed_column_sets


def test_exercise_muscle_has_role_and_non_blank_constraints() -> None:
    constraint_names = {constraint.name for constraint in ExerciseMuscle.__table__.constraints}

    assert "ck_exercise_muscles_role" in constraint_names
    assert "ck_exercise_muscles_muscle_code_not_blank" in constraint_names


def test_exercise_alias_has_cascade_foreign_key() -> None:
    exercise_foreign_key = next(iter(ExerciseAlias.__table__.c.exercise_id.foreign_keys))

    assert exercise_foreign_key.target_fullname == "exercises.id"
    assert exercise_foreign_key.ondelete == "CASCADE"


def test_exercise_alias_is_unique_per_exercise_after_normalization() -> None:
    constraint_names = {constraint.name for constraint in ExerciseAlias.__table__.constraints}

    assert "uq_exercise_aliases_exercise_normalized" in constraint_names
    assert "ck_exercise_aliases_alias_not_blank" in constraint_names
    assert "ck_exercise_aliases_normalized_alias_not_blank" in constraint_names


def test_exercise_alias_has_lookup_indexes() -> None:
    indexed_column_sets = {
        tuple(column.name for column in index.columns) for index in ExerciseAlias.__table__.indexes
    }

    assert ("exercise_id",) in indexed_column_sets
    assert ("normalized_alias",) in indexed_column_sets


def test_exercise_substitution_references_source_and_target_with_cascade() -> None:
    table = ExerciseSubstitution.__table__
    source_foreign_key = next(iter(table.c.source_exercise_id.foreign_keys))
    target_foreign_key = next(iter(table.c.target_exercise_id.foreign_keys))

    assert source_foreign_key.target_fullname == "exercises.id"
    assert source_foreign_key.ondelete == "CASCADE"
    assert target_foreign_key.target_fullname == "exercises.id"
    assert target_foreign_key.ondelete == "CASCADE"


def test_exercise_substitution_has_safety_and_uniqueness_constraints() -> None:
    constraint_names = {
        constraint.name for constraint in ExerciseSubstitution.__table__.constraints
    }

    assert "ck_exercise_substitutions_different_exercises" in constraint_names
    assert "ck_exercise_substitutions_reason_not_blank" in constraint_names
    assert "ck_exercise_substitutions_priority_positive" in constraint_names
    assert "uq_exercise_substitutions_source_target" in constraint_names


def test_exercise_substitution_has_directional_lookup_indexes() -> None:
    indexed_column_sets = {
        tuple(column.name for column in index.columns)
        for index in ExerciseSubstitution.__table__.indexes
    }

    assert ("source_exercise_id", "priority") in indexed_column_sets
    assert ("target_exercise_id",) in indexed_column_sets


def test_exercise_media_has_cascade_foreign_key() -> None:
    exercise_foreign_key = next(iter(ExerciseMedia.__table__.c.exercise_id.foreign_keys))

    assert exercise_foreign_key.target_fullname == "exercises.id"
    assert exercise_foreign_key.ondelete == "CASCADE"


def test_exercise_media_has_type_storage_and_order_constraints() -> None:
    constraint_names = {constraint.name for constraint in ExerciseMedia.__table__.constraints}

    assert "ck_exercise_media_media_type" in constraint_names
    assert "ck_exercise_media_storage_key_not_blank" in constraint_names
    assert "ck_exercise_media_sort_order_positive" in constraint_names
    assert "uq_exercise_media_storage_key" in constraint_names


def test_exercise_media_has_ordered_exercise_index() -> None:
    indexed_column_sets = {
        tuple(column.name for column in index.columns) for index in ExerciseMedia.__table__.indexes
    }

    assert ("exercise_id", "sort_order") in indexed_column_sets
