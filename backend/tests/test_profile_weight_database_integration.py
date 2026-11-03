"""Run only on request; all synthetic records are rolled back."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import BodyMeasurement, Profile, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.repositories.profile import SqlAlchemyProfileRepository
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.profile import ProfileService, ProfileVersionConflictError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_profile_weight_is_immediately_visible_shared_and_rollback_safe():
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            owner = User(username=f"profile-weight-{uuid4().hex}", password_setup_required=False)
            other = User(username=f"profile-other-{uuid4().hex}", password_setup_required=False)
            session.add_all([owner, other])
            await session.flush()
            session.add(Profile(user_id=owner.id, version=1))
            repo = SqlAlchemyBodyRepository(session)
            await repo.add_measurement(
                BodyMeasurement(
                    user_id=other.id, measured_at=datetime.now(UTC), weight_kg=99, source="test"
                )
            )
            await session.flush()
            service = ProfileService(SqlAlchemyProfileRepository(session), repo)
            await service.update_profile(
                user_id=owner.id,
                changes={"height_cm": Decimal("173"), "weight_kg": Decimal("70.5")},
                expected_version=1,
            )
            summary = await BodyService(repo).recent_measurement_summary(owner.id)
            assert summary["weight_kg"] == "70.5"
            # A future entry and unrelated recent measurements must not hide the latest weight.
            await repo.add_measurement(
                BodyMeasurement(
                    user_id=owner.id,
                    measured_at=datetime.now(UTC) + timedelta(days=5),
                    weight_kg=80,
                    source="test",
                )
            )
            session.add_all(
                [
                    BodyMeasurement(
                        user_id=owner.id, measured_at=datetime.now(UTC), waist_cm=80, source="test"
                    )
                    for _ in range(105)
                ]
            )
            await session.flush()
            assert (await BodyService(repo).recent_measurement_summary(owner.id))[
                "weight_kg"
            ] == "70.5"
            with pytest.raises(ProfileVersionConflictError):
                await service.update_profile(
                    user_id=owner.id, changes={"weight_kg": Decimal("70.5")}, expected_version=1
                )
            count = await session.scalar(
                select(func.count())
                .select_from(BodyMeasurement)
                .where(BodyMeasurement.user_id == owner.id, BodyMeasurement.source == "profile")
            )
            assert count == 1
        finally:
            await transaction.rollback()
