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
    repository.list_measurements = AsyncMock(
        return_value=(
            [
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
            ],
            2,
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
    repository.list_measurements.assert_awaited_once_with(
        user_id, None, None, 1, 100
    )


@pytest.mark.asyncio
async def test_missing_body_measurements_remain_missing() -> None:
    repository = MagicMock()
    repository.list_measurements = AsyncMock(return_value=([], 0))

    summary = await BodyService(repository).recent_measurement_summary(uuid4())

    assert all(value is None for value in summary.values())
