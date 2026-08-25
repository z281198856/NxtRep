from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.profile import ProfileUpdateRequest


def test_profile_update_accepts_partial_fields() -> None:
    request = ProfileUpdateRequest(
        display_name="  思琪  ",
        weekly_training_days=3,
        expected_version=1,
    )

    assert request.display_name == "思琪"
    assert request.weekly_training_days == 3
    assert request.model_fields_set == {
        "display_name",
        "weekly_training_days",
        "expected_version",
    }


def test_profile_update_requires_changed_field() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(expected_version=1)


def test_profile_update_rejects_future_birth_date() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(
            birth_date=date.today() + timedelta(days=1),
            expected_version=1,
        )


def test_profile_update_converts_null_sex_to_unspecified() -> None:
    request = ProfileUpdateRequest(
        sex=None,
        expected_version=1,
    )

    assert request.sex == "unspecified"


def test_profile_update_rejects_manually_supplied_timezone() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdateRequest.model_validate(
            {
                "timezone": "Asia/Tokyo",
                "expected_version": 1,
            }
        )
