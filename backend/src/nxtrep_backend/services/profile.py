from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nxtrep_backend.db.models import BodyMeasurement, Confirmation, Profile
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.profile import (
    SqlAlchemyProfileRepository,
)
from nxtrep_backend.schemas.profile import ProfileResponse, ProfileUpdateRequest

PROFILE_UPDATE_FIELDS = frozenset(
    {
        "display_name",
        "sex",
        "birth_date",
        "height_cm",
        "weight_kg",
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
        body_repository: SqlAlchemyBodyRepository | None = None,
        confirmations: SqlAlchemyConfirmationRepository | None = None,
    ) -> None:
        self._repository = repository
        self._body_repository = body_repository
        self._confirmations = confirmations

    async def read_update_snapshot(self, user_id: UUID) -> dict:
        profile = await self.get_profile(user_id=user_id)
        snapshot = ProfileResponse.model_validate(profile).model_dump(mode="json")
        if self._body_repository is not None:
            weight = await self._body_repository.latest_measurement(user_id, "weight_kg")
            snapshot["weight_kg"] = str(weight.weight_kg) if weight else None
            snapshot["weight_recorded_at"] = (
                weight.measured_at.date().isoformat() if weight else None
            )
        return snapshot

    async def propose_update(self, user_id: UUID, body: ProfileUpdateRequest) -> Confirmation:
        if self._confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        before = await self.read_update_snapshot(user_id)
        if before["version"] != body.expected_version:
            raise ProfileVersionConflictError(
                expected_version=body.expected_version, current_version=before["version"]
            )
        changes = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_version"})
        if "weight_kg" in changes and changes["weight_kg"] is None:
            raise ValueError("体重不能通过资料草稿清空；删除测量需在身体记录中单独处理。")
        return await self._confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="profile_update",
                before={"profile": before},
                after={"changes": changes, "expected_version": body.expected_version},
                reason="用户请求修改个人资料",
                impact=(
                    "确认后仅更新所列个人资料；已有训练计划和营养目标保持原值。"
                    + ("体重会新增一条当前测量，保留历史记录。" if "weight_kg" in changes else "")
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

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

        weight = changes.get("weight_kg")
        if weight is not None:
            if self._body_repository is None:
                raise ValueError("Body repository is required to record weight")
            # Same request transaction and profile version lock: no split saves or lost history.
            await self._body_repository.add_measurement(
                BodyMeasurement(
                    user_id=user_id,
                    measured_at=datetime.now(UTC),
                    weight_kg=weight,
                    source="profile",
                    notes="个人资料更新体重",
                )
            )
        for field_name, value in changes.items():
            if field_name != "weight_kg":
                setattr(profile, field_name, value)

        profile.version += 1

        return profile

    async def get_profile(
        self,
        *,
        user_id: UUID,
    ) -> Profile:
        profile = await self._repository.get_by_user_id(
            user_id,
        )

        if profile is None:
            raise ProfileNotFoundError("Profile not found")

        return profile
