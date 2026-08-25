from sqlalchemy.dialects.postgresql import JSONB

from nxtrep_backend.db.models import GoalStatus, GoalType, UserConstraint, UserGoal


def test_goal_enums_match_api_contract() -> None:
    assert {item.value for item in GoalType} == {
        "muscle_gain",
        "fat_loss_retain",
        "recomposition",
        "maintain",
        "strength",
    }
    assert {item.value for item in GoalStatus} == {"active", "superseded"}


def test_goal_and_constraint_tables_have_expected_shape() -> None:
    assert UserGoal.__tablename__ == "user_goals"
    assert UserConstraint.__tablename__ == "user_constraints"
    assert UserConstraint.__table__.c.user_id.primary_key

    json_columns = {
        "equipment",
        "preferred_exercise_ids",
        "disliked_exercise_ids",
        "pain_or_injuries",
        "allergies",
        "dietary_preferences",
    }
    assert json_columns <= set(UserConstraint.__table__.c.keys())
    assert all(
        isinstance(UserConstraint.__table__.c[column_name].type, JSONB)
        for column_name in json_columns
    )


def test_only_one_active_goal_index_is_defined() -> None:
    active_index = next(
        index
        for index in UserGoal.__table__.indexes
        if index.name == "uq_user_goals_one_active_per_user"
    )
    assert active_index.unique
    assert str(active_index.dialect_options["postgresql"]["where"]) == "status = 'active'"
