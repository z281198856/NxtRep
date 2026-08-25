from collections.abc import Mapping
from uuid import UUID

from nxtrep_backend.db.models import Profile
from nxtrep_backend.repositories.profile import (
    SqlAlchemyProfileRepository,
)

PROFILE_UPDATE_FIELDS = frozenset(
    {
        "display_name",
        "sex",
        "birth_date",
        "height_cm",
        "experience_level",
        "weekly_training_days",
        "session_duration_minutes",
    }
)


class ProfileNotFoundError(RuntimeError):
    """当前用户的个人档案不存在。"""


class ProfileVersionConflictError(RuntimeError):
    """客户端提交的档案版本已经过期。"""

    def __init__(
        self,
        *,
        expected_version: int,
        current_version: int,
    ) -> None:
        super().__init__("Profile version conflict")
        self.expected_version = expected_version
        self.current_version = current_version


class ProfileService:
    def __init__(
        self,
        repository: SqlAlchemyProfileRepository,
    ) -> None:
        self._repository = repository

    async def update_profile(
        self,
        *,
        user_id: UUID,
        changes: Mapping[str, object],
        expected_version: int,
    ) -> Profile:
        if not changes:
            raise ValueError("At least one profile field must be provided")

        unexpected_fields = set(changes) - PROFILE_UPDATE_FIELDS

        if unexpected_fields:
            raise ValueError(f"Unsupported profile fields: {sorted(unexpected_fields)}")

        profile = await self._repository.get_by_user_id(
            user_id,
            for_update=True,
        )

        if profile is None:
            raise ProfileNotFoundError("Profile not found")

        if profile.version != expected_version:
            raise ProfileVersionConflictError(
                expected_version=expected_version,
                current_version=profile.version,
            )

        for field_name, value in changes.items():
            setattr(profile, field_name, value)

        profile.version += 1

        return profile
