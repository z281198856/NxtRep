import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.settings import SettingsUpdateRequest


def test_settings_update_accepts_valid_timezone() -> None:
    request = SettingsUpdateRequest(
        timezone=" Asia/Tokyo ",
        expected_version=1,
    )

    assert request.timezone == "Asia/Tokyo"


def test_settings_update_rejects_invalid_timezone() -> None:
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        SettingsUpdateRequest(timezone="Mars/Olympus", expected_version=1)


def test_settings_update_requires_a_changed_field() -> None:
    with pytest.raises(ValidationError, match="At least one settings field"):
        SettingsUpdateRequest(expected_version=1)
