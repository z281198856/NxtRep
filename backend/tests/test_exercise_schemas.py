from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.exercise import (
    ExerciseCreateRequest,
    ExerciseDetailResponse,
    ExerciseListItemResponse,
    ExerciseListQuery,
    ExerciseListResponse,
    ExerciseSubstitutionResponse,
    ExerciseUpdateRequest,
)


def test_exercise_list_query_uses_pagination_defaults() -> None:
    query = ExerciseListQuery()

    assert query.keyword is None
    assert query.equipment is None
    assert query.muscle is None
    assert query.page == 1
    assert query.page_size == 20


def test_exercise_list_query_strips_filter_whitespace() -> None:
    query = ExerciseListQuery(
        keyword="  深蹲  ",
        equipment="  barbell  ",
        muscle="  quadriceps  ",
    )

    assert query.keyword == "深蹲"
    assert query.equipment == "barbell"
    assert query.muscle == "quadriceps"


@pytest.mark.parametrize("field", ["equipment", "muscle"])
def test_exercise_list_query_rejects_invalid_codes(field: str) -> None:
    with pytest.raises(ValidationError):
        ExerciseListQuery.model_validate({field: "Upper Body"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page", 0),
        ("page_size", 0),
        ("page_size", 101),
    ],
)
def test_exercise_list_query_rejects_invalid_pagination(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        ExerciseListQuery.model_validate({field: value})


def test_exercise_list_query_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ExerciseListQuery.model_validate({"sort": "name"})


def test_exercise_list_response_serializes_api_shape() -> None:
    exercise_id = uuid4()
    item = ExerciseListItemResponse(
        id=exercise_id,
        name_zh="杠铃深蹲",
        aliases=["深蹲"],
        equipment="barbell",
        primary_muscles=["quadriceps", "gluteus"],
        is_custom=False,
    )
    response = ExerciseListResponse(
        list=[item],
        total=1,
        page=1,
        page_size=20,
        has_more=False,
    )

    assert response.model_dump(mode="json") == {
        "list": [
            {
                "id": str(exercise_id),
                "name_zh": "杠铃深蹲",
                "aliases": ["深蹲"],
                "equipment": "barbell",
                "primary_muscles": ["quadriceps", "gluteus"],
                "is_custom": False,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "has_more": False,
    }


def test_exercise_detail_response_serializes_api_shape() -> None:
    exercise_id = uuid4()
    substitution_id = uuid4()
    response = ExerciseDetailResponse(
        id=exercise_id,
        name_zh="杠铃深蹲",
        aliases=["深蹲"],
        movement_pattern="squat",
        equipment="barbell",
        difficulty="intermediate",
        primary_muscles=["quadriceps", "gluteus"],
        secondary_muscles=["hamstring"],
        instructions=["站稳并收紧核心"],
        breathing=["下蹲时吸气"],
        common_errors=["膝盖内扣"],
        safety_notes=["出现疼痛时停止动作"],
        substitutions=[
            ExerciseSubstitutionResponse(
                id=substitution_id,
                name_zh="高脚杯深蹲",
                equipment="dumbbell",
                reason="无杠铃时可替代",
            )
        ],
        notes=None,
        version=1,
        is_custom=False,
    )

    payload = response.model_dump(mode="json")

    assert payload["id"] == str(exercise_id)
    assert payload["aliases"] == ["深蹲"]
    assert payload["breathing"] == ["下蹲时吸气"]
    assert payload["substitutions"] == [
        {
            "id": str(substitution_id),
            "name_zh": "高脚杯深蹲",
            "equipment": "dumbbell",
            "reason": "无杠铃时可替代",
        }
    ]
    assert payload["version"] == 1
    assert payload["is_custom"] is False


def test_exercise_detail_response_rejects_non_positive_version() -> None:
    with pytest.raises(ValidationError):
        ExerciseDetailResponse(
            id=uuid4(),
            name_zh="深蹲",
            aliases=[],
            movement_pattern=None,
            equipment="bodyweight",
            difficulty=None,
            primary_muscles=[],
            secondary_muscles=[],
            instructions=[],
            breathing=[],
            common_errors=[],
            safety_notes=[],
            substitutions=[],
            notes=None,
            version=0,
            is_custom=False,
        )


def test_exercise_create_request_accepts_and_normalizes_valid_data() -> None:
    request = ExerciseCreateRequest(
        name_zh="  高脚杯深蹲  ",
        equipment="  dumbbell  ",
        primary_muscles=[" quadriceps ", "gluteus"],
        secondary_muscles=["hamstring"],
        notes="  家里训练使用  ",
    )

    assert request.name_zh == "高脚杯深蹲"
    assert request.equipment == "dumbbell"
    assert request.primary_muscles == ["quadriceps", "gluteus"]
    assert request.secondary_muscles == ["hamstring"]
    assert request.notes == "家里训练使用"


def test_exercise_create_request_requires_primary_muscle() -> None:
    with pytest.raises(ValidationError):
        ExerciseCreateRequest(
            name_zh="高脚杯深蹲",
            equipment="dumbbell",
            primary_muscles=[],
        )


def test_exercise_create_request_rejects_duplicate_muscles() -> None:
    with pytest.raises(ValidationError):
        ExerciseCreateRequest(
            name_zh="高脚杯深蹲",
            equipment="dumbbell",
            primary_muscles=["quadriceps", "quadriceps"],
        )


def test_exercise_create_request_rejects_primary_secondary_overlap() -> None:
    with pytest.raises(ValidationError):
        ExerciseCreateRequest(
            name_zh="高脚杯深蹲",
            equipment="dumbbell",
            primary_muscles=["quadriceps"],
            secondary_muscles=["quadriceps"],
        )


def test_exercise_create_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ExerciseCreateRequest.model_validate(
            {
                "name_zh": "高脚杯深蹲",
                "equipment": "dumbbell",
                "primary_muscles": ["quadriceps"],
                "movement_pattern": "squat",
            }
        )


def test_exercise_update_request_accepts_partial_update() -> None:
    request = ExerciseUpdateRequest(
        name_zh="  新动作名称  ",
        expected_version=2,
    )

    assert request.name_zh == "新动作名称"
    assert request.expected_version == 2
    assert request.model_fields_set == {"name_zh", "expected_version"}


def test_exercise_update_request_allows_explicitly_clearing_notes() -> None:
    request = ExerciseUpdateRequest(
        notes=None,
        expected_version=2,
    )

    assert request.notes is None
    assert "notes" in request.model_fields_set


def test_exercise_update_request_requires_actual_update_field() -> None:
    with pytest.raises(ValidationError):
        ExerciseUpdateRequest(expected_version=2)


def test_exercise_update_request_requires_expected_version() -> None:
    with pytest.raises(ValidationError):
        ExerciseUpdateRequest(name_zh="新动作名称")


@pytest.mark.parametrize(
    "field_name",
    [
        "name_zh",
        "equipment",
        "primary_muscles",
        "secondary_muscles",
    ],
)
def test_exercise_update_request_rejects_null_for_required_resource_fields(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError):
        ExerciseUpdateRequest.model_validate(
            {
                field_name: None,
                "expected_version": 2,
            }
        )


def test_exercise_update_request_rejects_duplicate_muscles() -> None:
    with pytest.raises(ValidationError):
        ExerciseUpdateRequest(
            primary_muscles=["quadriceps", "quadriceps"],
            expected_version=2,
        )


def test_exercise_update_request_rejects_supplied_muscle_overlap() -> None:
    with pytest.raises(ValidationError):
        ExerciseUpdateRequest(
            primary_muscles=["quadriceps"],
            secondary_muscles=["quadriceps"],
            expected_version=2,
        )
