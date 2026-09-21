from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.profile import build_profile_tools
from nxtrep_backend.db.models import Profile
from nxtrep_backend.services.goals import GoalsService
from nxtrep_backend.services.profile import (
    ProfileNotFoundError,
    ProfileService,
)


def make_profile(*, birth_date: date | None) -> Profile:
    return Profile(
        user_id=uuid4(),
        display_name="不应提供给模型",
        sex="female",
        birth_date=birth_date,
        height_cm=Decimal("168.50"),
        experience_level="beginner",
        weekly_training_days=3,
        session_duration_minutes=60,
        timezone="Asia/Shanghai",
        version=2,
    )


def make_profile_service() -> MagicMock:
    service = MagicMock(spec=ProfileService)
    service.get_profile = AsyncMock()
    return service


def build_profile_tool(*, user_id, profile_service):
    context = MagicMock(spec=AgentToolContext)
    context.user_id = user_id
    context.profile_service = profile_service
    context.goals_service = MagicMock(spec=GoalsService)
    return build_profile_tools(context)[0]


@pytest.mark.asyncio
async def test_profile_tool_returns_minimum_fitness_context() -> None:
    user_id = uuid4()
    service = make_profile_service()
    service.get_profile.return_value = make_profile(
        birth_date=date(2000, 6, 15),
    )
    profile_tool = build_profile_tool(
        user_id=user_id,
        profile_service=service,
    )

    with patch(
        "nxtrep_backend.agents.tools.profile.date",
    ) as mocked_date:
        mocked_date.today.return_value = date(2026, 9, 3)
        result = await profile_tool.ainvoke({})

    service.get_profile.assert_awaited_once_with(user_id=user_id)
    assert result == {
        "status": "available",
        "profile": {
            "sex": "female",
            "age_years": 26,
            "height_cm": "168.50",
            "experience_level": "beginner",
            "weekly_training_days": 3,
            "session_duration_minutes": 60,
            "timezone": "Asia/Shanghai",
        },
    }
    assert "display_name" not in result["profile"]
    assert "version" not in result["profile"]


@pytest.mark.asyncio
async def test_profile_tool_calculates_age_before_birthday() -> None:
    service = make_profile_service()
    service.get_profile.return_value = make_profile(
        birth_date=date(2000, 12, 20),
    )
    profile_tool = build_profile_tool(
        user_id=uuid4(),
        profile_service=service,
    )

    with patch(
        "nxtrep_backend.agents.tools.profile.date",
    ) as mocked_date:
        mocked_date.today.return_value = date(2026, 9, 3)
        result = await profile_tool.ainvoke({})

    assert result["profile"]["age_years"] == 25


@pytest.mark.asyncio
async def test_profile_tool_handles_missing_profile() -> None:
    service = make_profile_service()
    service.get_profile.side_effect = ProfileNotFoundError("Profile not found")
    profile_tool = build_profile_tool(
        user_id=uuid4(),
        profile_service=service,
    )

    result = await profile_tool.ainvoke({})

    assert result == {
        "status": "not_configured",
        "message": "The user has not configured a profile.",
    }


@pytest.mark.asyncio
async def test_profile_tool_has_no_model_controlled_user_id_argument() -> None:
    service = make_profile_service()
    service.get_profile.return_value = make_profile(birth_date=None)
    bound_user_id = uuid4()
    profile_tool = build_profile_tool(
        user_id=bound_user_id,
        profile_service=service,
    )

    assert profile_tool.name == "read_profile_summary"
    assert profile_tool.args_schema.model_json_schema()["properties"] == {}

    await profile_tool.ainvoke({})

    service.get_profile.assert_awaited_once_with(user_id=bound_user_id)
