from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.platform import NotificationSettingsUpdate
from nxtrep_backend.services.notification_timing import coach_paused, coach_quiet


@pytest.mark.parametrize("hour,quiet", [(13, False), (14, True), (23, True), (0, False)])
def test_cross_midnight_quiet_hours_use_user_timezone(hour, quiet):
    config = {"enabled": True, "start": "22:00", "end": "08:00", "timezone": "Asia/Shanghai"}
    assert coach_quiet(config, datetime(2026, 10, 5, hour, tzinfo=UTC)) == quiet


@pytest.mark.parametrize(
    "config",
    [
        {"start": "25:00"},
        {"start": "08:00", "end": "08:00"},
        {"timezone": "invalid-zone"},
        {"pause_until": "2026-10-06T00:00:00"},
    ],
)
def test_invalid_settings_rejected_before_storage(config):
    with pytest.raises(ValidationError):
        NotificationSettingsUpdate(expected_version=1, quiet_hours=config)


def test_pause_expiry_and_resume():
    now = datetime(2026, 10, 5, 1, tzinfo=UTC)
    assert coach_paused({"pause_until": "2026-10-05T02:00:00+00:00"}, now)
    assert not coach_paused({"pause_until": now.isoformat()}, now)
    assert not coach_paused(None, now)
