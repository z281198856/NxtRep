import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from nxtrep_backend.db.models import AgentMemory, BodyMeasurement, Profile, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
from nxtrep_backend.schemas.profile import ProfileUpdateRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.profile import ProfileService, ProfileVersionConflictError

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"profile-draft-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    profile = Profile(
        user_id=user.id,
        display_name="验收用户",
        height_cm=170,
        sex="unspecified",
        experience_level="beginner",
        weekly_training_days=3,
        session_duration_minutes=45,
    )
    session.add(profile)
    await session.flush()
    commands = SqlAlchemyConfirmationRepository(session)
    service = ProfileService(
        SqlAlchemyProfileRepository(session), SqlAlchemyBodyRepository(session), commands
    )
    return user, profile, service, DatabaseConfirmationService(commands)


@pytest.mark.asyncio
async def test_profile_changes_only_after_approval_and_weight_is_append_only():
    async with SessionFactory() as session:
        try:
            user, profile, service, commands = await seed(session)
            await service.update_profile(
                user_id=user.id, changes={"weight_kg": Decimal("70")}, expected_version=1
            )
            card = await service.propose_update(
                user.id,
                ProfileUpdateRequest(
                    expected_version=2, height_cm=175, weekly_training_days=4, weight_kg=71.5
                ),
            )
            assert profile.height_cm == 170 and profile.version == 2
            assert card.before["profile"]["weight_kg"] == "70.000"
            assert set(card.after["changes"]) == {"height_cm", "weekly_training_days", "weight_kg"}
            count = (
                select(func.count())
                .select_from(BodyMeasurement)
                .where(BodyMeasurement.user_id == user.id)
            )
            assert await session.scalar(count) == 1
            await commands.approve(user.id, card.id, card.version)
            assert profile.height_cm == 175 and profile.weekly_training_days == 4
            assert profile.session_duration_minutes == 45 and profile.experience_level == "beginner"
            assert profile.version == 3 and await session.scalar(count) == 2
            weights = list(
                await session.scalars(
                    select(BodyMeasurement.weight_kg).where(BodyMeasurement.user_id == user.id)
                )
            )
            assert sorted(weights) == [Decimal("70"), Decimal("71.5")]
            assert (await service.read_update_snapshot(user.id))["weight_kg"] == "71.500"
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, 1)
            assert await session.scalar(count) == 2
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMemory)
                    .where(AgentMemory.user_id == user.id)
                )
                == 0
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_rejected_or_cancelled_profile_draft_does_not_write(decision):
    async with SessionFactory() as session:
        try:
            user, profile, service, commands = await seed(session)
            card = await service.propose_update(
                user.id, ProfileUpdateRequest(expected_version=1, height_cm=180)
            )
            if decision == "reject":
                await commands.reject(user.id, card.id, card.version, "保留原资料")
            else:
                await commands.cancel(user.id, card.id, card.version)
            assert profile.height_cm == 170 and profile.version == 1
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, 1)
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_profile_stale_draft_and_other_user_cannot_overwrite():
    async with SessionFactory() as session:
        try:
            user, profile, service, commands = await seed(session)
            card = await service.propose_update(
                user.id, ProfileUpdateRequest(expected_version=1, height_cm=180)
            )
            with pytest.raises(DatabaseConfirmationNotFoundError):
                await commands.approve(uuid4(), card.id, 1)
            await service.update_profile(
                user_id=user.id, changes={"height_cm": Decimal("173")}, expected_version=1
            )
            with pytest.raises(DatabaseConfirmationConflictError, match="个人资料已被修改"):
                await commands.approve(user.id, card.id, 1)
            assert profile.height_cm == 173 and profile.version == 2 and card.status == "pending"
            with pytest.raises(ProfileVersionConflictError):
                await service.propose_update(
                    user.id, ProfileUpdateRequest(expected_version=1, height_cm=180)
                )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_profile_explicit_clear_preserves_other_fields_but_cannot_clear_weight():
    async with SessionFactory() as session:
        try:
            user, profile, service, commands = await seed(session)
            with pytest.raises(ValueError, match="体重不能"):
                await service.propose_update(
                    user.id, ProfileUpdateRequest(expected_version=1, weight_kg=None)
                )
            card = await service.propose_update(
                user.id, ProfileUpdateRequest(expected_version=1, display_name=None)
            )
            await commands.approve(user.id, card.id, 1)
            assert profile.display_name is None and profile.height_cm == 170
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_profile_approval_refreshes_already_loaded_profile_before_version_check():
    async with SessionFactory() as session:
        try:
            user, profile, service, commands = await seed(session)
            card = await service.propose_update(
                user.id, ProfileUpdateRequest(expected_version=1, height_cm=180)
            )
            await session.execute(
                update(Profile)
                .where(Profile.user_id == user.id)
                .values(height_cm=173, version=2)
                .execution_options(synchronize_session=False)
            )
            assert (
                profile.version == 1
            )  # Identity map holds a snapshot from before the newer write.
            with pytest.raises(DatabaseConfirmationConflictError, match="个人资料已被修改"):
                await commands.approve(user.id, card.id, 1)
            assert profile.height_cm == 173 and profile.version == 2
        finally:
            await session.rollback()
