from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.body import (
    build_body_draft_tools,
    build_body_read_tools,
)
from nxtrep_backend.services.body import BodyService


def make_context() -> MagicMock:
    context = MagicMock(spec=AgentToolContext)
    context.user_id = uuid4()
    context.body_service = MagicMock(spec=BodyService)
    context.body_service.navy_body_fat = AsyncMock()
    context.body_service.propose_measurement = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_body_fat_tool_never_saves_calculation() -> None:
    context = make_context()
    context.body_service.navy_body_fat.return_value = {
        "method": "navy",
        "value_percent": 20,
        "range_min_percent": 17,
        "range_max_percent": 23,
        "confidence": "medium",
    }
    current_tool = next(
        item
        for item in build_body_read_tools(context)
        if item.name == "calculate_navy_body_fat_range"
    )

    result = await current_tool.ainvoke(
        {
            "sex": "male",
            "height_cm": "180",
            "waist_cm": "85",
            "neck_cm": "38",
        }
    )

    assert result["status"] == "available"
    request = context.body_service.navy_body_fat.await_args.args[1]
    assert request.save is False


@pytest.mark.asyncio
async def test_body_measurement_tool_creates_confirmation() -> None:
    context = make_context()
    confirmation = SimpleNamespace(
        id=uuid4(),
        operation_type="body_measurement_create",
        status="pending",
        before=None,
        after={"measurement": {}},
        impact="save measurement",
        expires_at=None,
        version=1,
    )
    context.body_service.propose_measurement.return_value = confirmation
    current_tool = build_body_draft_tools(context)[0]

    result = await current_tool.ainvoke(
        {
            "measured_at": datetime(2026, 9, 3, 8, tzinfo=UTC).isoformat(),
            "source": "manual",
            "weight_kg": "70.5",
        }
    )

    assert result["status"] == "confirmation_required"
    request = context.body_service.propose_measurement.await_args.kwargs["body"]
    assert str(request.weight_kg) == "70.5"
