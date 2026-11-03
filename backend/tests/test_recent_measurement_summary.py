from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.services.body import BodyService


@pytest.mark.asyncio
async def test_latest_weight_and_body_fat_can_come_from_different_records() -> None:
    repository = MagicMock()
    repository.latest_measurement = AsyncMock(
        side_effect=(
            SimpleNamespace(
                measured_at=datetime(2026, 9, 25, tzinfo=UTC),
                weight_kg=Decimal("78.5"),
                body_fat_percent=None,
                body_fat_method=None,
            ),
            SimpleNamespace(
                measured_at=datetime(2026, 9, 20, tzinfo=UTC),
                weight_kg=None,
                body_fat_percent=Decimal("24.0"),
                body_fat_method="manual",
            ),
        )
    )
    user_id = uuid4()

    summary = await BodyService(repository).recent_measurement_summary(user_id)

    assert summary == {
        "weight_kg": "78.5",
        "weight_recorded_at": "2026-09-25",
        "body_fat_percent": "24",
        "body_fat_recorded_at": "2026-09-20",
        "body_fat_method": "manual",
    }
    assert repository.latest_measurement.await_args_list[0].args == (user_id, "weight_kg")
    assert repository.latest_measurement.await_args_list[1].args == (user_id, "body_fat_percent")


@pytest.mark.asyncio
async def test_missing_body_measurements_remain_missing() -> None:
    repository = MagicMock()
    repository.latest_measurement = AsyncMock(return_value=None)

    summary = await BodyService(repository).recent_measurement_summary(uuid4())

    assert all(value is None for value in summary.values())
