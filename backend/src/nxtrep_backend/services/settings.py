from uuid import UUID

from nxtrep_backend.db.models import UserSettings
from nxtrep_backend.repositories.settings import SqlAlchemySettingsRepository


class SettingsVersionConflictError(RuntimeError):
    def __init__(self, *, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__("Settings have been modified")


class SettingsService:
    def __init__(self, repository: SqlAlchemySettingsRepository) -> None:
        self._repository = repository

    async def get(self, *, user_id: UUID) -> UserSettings:
        settings = await self._repository.get(user_id)
        if settings is not None:
            return settings
        return await self._repository.add(UserSettings(user_id=user_id))

    async def update(
        self,
        *,
        user_id: UUID,
        changes: dict[str, object],
        expected_version: int,
    ) -> UserSettings:
        settings = await self._repository.get(user_id, for_update=True)
        if settings is None:
            settings = await self._repository.add(UserSettings(user_id=user_id))
        if settings.version != expected_version:
            raise SettingsVersionConflictError(
                expected_version=expected_version,
                current_version=settings.version,
            )

        for field, value in changes.items():
            setattr(settings, field, value)
        settings.version += 1

        if "timezone" in changes:
            profile = await self._repository.get_profile_for_update(user_id)
            if profile is not None:
                profile.timezone = str(changes["timezone"])
                profile.version += 1
        return settings
