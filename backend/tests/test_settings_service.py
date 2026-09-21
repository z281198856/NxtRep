from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import Profile, UserSettings
from nxtrep_backend.repositories.settings import SqlAlchemySettingsRepository
from nxtrep_backend.services.settings import (
    SettingsService,
    SettingsVersionConflictError,
)


@pytest.mark.asyncio
async def test_get_creates_defaults_for_legacy_user() -> None:
    repository = MagicMock(spec=SqlAlchemySettingsRepository)
    repository.get = AsyncMock(return_value=None)
    repository.add = AsyncMock(side_effect=lambda item: item)
    user_id = uuid4()

    result = await SettingsService(repository).get(user_id=user_id)

    assert result.user_id == user_id
    assert result.unit_system is None or result.unit_system == "metric"
    repository.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_uses_version_and_syncs_profile_timezone() -> None:
    user_id = uuid4()
    item = UserSettings(
        user_id=user_id,
        unit_system="metric",
        timezone="Asia/Shanghai",
        privacy_mode="private",
        share_anonymous_analytics=False,
        version=1,
    )
    profile = Profile(user_id=user_id, timezone="Asia/Shanghai", version=3)
    repository = MagicMock(spec=SqlAlchemySettingsRepository)
    repository.get = AsyncMock(return_value=item)
    repository.get_profile_for_update = AsyncMock(return_value=profile)

    result = await SettingsService(repository).update(
        user_id=user_id,
        changes={"timezone": "Asia/Tokyo", "unit_system": "imperial"},
        expected_version=1,
    )

    assert result.version == 2
    assert result.timezone == "Asia/Tokyo"
    assert profile.timezone == "Asia/Tokyo"
    assert profile.version == 4


@pytest.mark.asyncio
async def test_update_rejects_stale_version() -> None:
    repository = MagicMock(spec=SqlAlchemySettingsRepository)
    repository.get = AsyncMock(return_value=UserSettings(version=4))

    with pytest.raises(SettingsVersionConflictError) as error:
        await SettingsService(repository).update(
            user_id=uuid4(),
            changes={"privacy_mode": "summary"},
            expected_version=3,
        )

    assert error.value.current_version == 4
