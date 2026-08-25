from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.db.models import Profile
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
from nxtrep_backend.services.profile import (
    ProfileNotFoundError,
    ProfileService,
    ProfileVersionConflictError,
)


@pytest.mark.asyncio
async def test_update_profile_changes_supplied_fields_and_increments_version() -> None:
    user_id = uuid4()
    profile = Profile(
        user_id=user_id,
        display_name=None,
        weekly_training_days=None,
        version=1,
    )
    repository = MagicMock(spec=SqlAlchemyProfileRepository)
    repository.get_by_user_id = AsyncMock(return_value=profile)
    service = ProfileService(repository)

    result = await service.update_profile(
        user_id=user_id,
        changes={
            "display_name": "思琪",
            "weekly_training_days": 3,
        },
        expected_version=1,
    )

    assert result is profile
    assert profile.display_name == "思琪"
    assert profile.weekly_training_days == 3
    assert profile.version == 2
    repository.get_by_user_id.assert_awaited_once_with(
        user_id,
        for_update=True,
    )


@pytest.mark.asyncio
async def test_update_profile_rejects_missing_profile() -> None:
    repository = MagicMock(spec=SqlAlchemyProfileRepository)
    repository.get_by_user_id = AsyncMock(return_value=None)
    service = ProfileService(repository)

    with pytest.raises(ProfileNotFoundError):
        await service.update_profile(
            user_id=uuid4(),
            changes={"display_name": "思琪"},
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_update_profile_reports_version_conflict() -> None:
    user_id = uuid4()
    profile = Profile(
        user_id=user_id,
        display_name="旧昵称",
        version=2,
    )
    repository = MagicMock(spec=SqlAlchemyProfileRepository)
    repository.get_by_user_id = AsyncMock(return_value=profile)
    service = ProfileService(repository)

    with pytest.raises(ProfileVersionConflictError) as error:
        await service.update_profile(
            user_id=user_id,
            changes={"display_name": "新昵称"},
            expected_version=1,
        )

    assert error.value.expected_version == 1
    assert error.value.current_version == 2
    assert profile.display_name == "旧昵称"
    assert profile.version == 2


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"timezone": "Asia/Tokyo"},
    ],
)
@pytest.mark.asyncio
async def test_update_profile_rejects_invalid_changes(
    changes: dict[str, object],
) -> None:
    repository = MagicMock(spec=SqlAlchemyProfileRepository)
    repository.get_by_user_id = AsyncMock()
    service = ProfileService(repository)

    with pytest.raises(ValueError):
        await service.update_profile(
            user_id=uuid4(),
            changes=changes,
            expected_version=1,
        )

    repository.get_by_user_id.assert_not_awaited()
