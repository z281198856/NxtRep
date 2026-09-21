from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.profile import build_profile_tools
from nxtrep_backend.db.models import UserConstraint, UserGoal
from nxtrep_backend.services.goals import (
    GoalsNotFoundError,
    GoalsService,
    GoalsStateError,
    GoalsUpdateResult,
)
from nxtrep_backend.services.profile import ProfileService


def make_goals_service() -> MagicMock:
    service = MagicMock(spec=GoalsService)
    service.get_goals_and_constraints = AsyncMock()
    return service


def build_goal_tool(
    *,
    user_id,
    goals_service,
):
    context = MagicMock(spec=AgentToolContext)
    context.user_id = user_id
    context.profile_service = MagicMock(spec=ProfileService)
    context.goals_service = goals_service
    tools = build_profile_tools(context)
    return next(tool for tool in tools if tool.name == "read_active_goal")


@pytest.mark.asyncio
async def test_goal_tool_returns_goal_and_safety_constraints() -> None:
    user_id = uuid4()
    preferred_id = uuid4()
    disliked_id = uuid4()
    goal = UserGoal(
        user_id=user_id,
        goal_type="strength",
        target_date=date(2027, 1, 1),
        target_weight_kg=Decimal("70.500"),
        status="active",
        version=3,
    )
    constraints = UserConstraint(
        user_id=user_id,
        equipment=["barbell", "rack"],
        preferred_exercise_ids=[str(preferred_id)],
        disliked_exercise_ids=[str(disliked_id)],
        pain_or_injuries=[
            {
                "area": "knee",
                "notes": "Deep flexion causes discomfort",
            }
        ],
        allergies=["peanut"],
        dietary_preferences=["high_protein"],
        version=3,
    )
    service = make_goals_service()
    service.get_goals_and_constraints.return_value = GoalsUpdateResult(
        goal=goal,
        constraints=constraints,
        warnings=["Review knee discomfort with a qualified professional."],
    )
    goal_tool = build_goal_tool(
        user_id=user_id,
        goals_service=service,
    )

    result = await goal_tool.ainvoke({})

    service.get_goals_and_constraints.assert_awaited_once_with(
        user_id=user_id,
    )
    assert result["status"] == "available"
    assert result["goal"] == {
        "goal_type": "strength",
        "target_date": "2027-01-01",
        "target_weight_kg": "70.500",
    }
    assert result["constraints"]["equipment"] == ["barbell", "rack"]
    assert result["constraints"]["pain_or_injuries"] == [
        {
            "area": "knee",
            "notes": "Deep flexion causes discomfort",
        }
    ]
    assert result["constraints"]["preferred_exercise_ids"] == [str(preferred_id)]
    assert "version" not in result["goal"]


@pytest.mark.asyncio
async def test_goal_tool_handles_unconfigured_goal() -> None:
    service = make_goals_service()
    service.get_goals_and_constraints.side_effect = GoalsNotFoundError(
        "Goals and constraints not found"
    )
    goal_tool = build_goal_tool(
        user_id=uuid4(),
        goals_service=service,
    )

    result = await goal_tool.ainvoke({})

    assert result == {
        "status": "not_configured",
        "message": "The user has not configured a goal and constraints.",
    }


@pytest.mark.asyncio
async def test_goal_tool_does_not_hide_inconsistent_database_state() -> None:
    service = make_goals_service()
    service.get_goals_and_constraints.side_effect = GoalsStateError(
        "Goal and constraints versions do not match"
    )
    goal_tool = build_goal_tool(
        user_id=uuid4(),
        goals_service=service,
    )

    with pytest.raises(GoalsStateError, match="versions do not match"):
        await goal_tool.ainvoke({})


def test_goal_tool_has_no_model_controlled_user_id_argument() -> None:
    goal_tool = build_goal_tool(
        user_id=uuid4(),
        goals_service=make_goals_service(),
    )

    assert goal_tool.args_schema.model_json_schema()["properties"] == {}
