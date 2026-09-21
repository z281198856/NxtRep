from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.exercise import build_exercise_tools
from nxtrep_backend.db.models import Exercise
from nxtrep_backend.repositories.exercise import ExerciseListEntry
from nxtrep_backend.services.exercise import ExerciseListResult, ExercisesService


def make_exercises_service() -> MagicMock:
    service = MagicMock(spec=ExercisesService)
    service.list_exercises = AsyncMock()
    return service


def build_exercise_tool(*, user_id, exercises_service):
    context = MagicMock(spec=AgentToolContext)
    context.user_id = user_id
    context.exercises_service = exercises_service
    tools = build_exercise_tools(context)
    return next(tool for tool in tools if tool.name == "search_exercises")


@pytest.mark.asyncio
async def test_search_exercises_returns_visible_catalog_rows() -> None:
    user_id = uuid4()
    exercise_id = uuid4()
    service = make_exercises_service()
    service.list_exercises.return_value = ExerciseListResult(
        items=[
            ExerciseListEntry(
                exercise=Exercise(
                    id=exercise_id,
                    owner_user_id=None,
                    name_zh="哑铃划船",
                    equipment="dumbbell",
                ),
                aliases=["单臂哑铃划船"],
                primary_muscles=["back"],
            )
        ],
        total=1,
        page=1,
        page_size=5,
        has_more=False,
    )
    exercise_tool = build_exercise_tool(
        user_id=user_id,
        exercises_service=service,
    )

    result = await exercise_tool.ainvoke(
        {
            "keyword": "划船",
            "equipment": "dumbbell",
            "muscle": "back",
            "limit": 5,
        }
    )

    service.list_exercises.assert_awaited_once_with(
        user_id=user_id,
        keyword="划船",
        equipment="dumbbell",
        muscle="back",
        page=1,
        page_size=5,
    )
    assert result == {
        "status": "available",
        "total": 1,
        "returned_count": 1,
        "has_more": False,
        "exercises": [
            {
                "id": str(exercise_id),
                "name_zh": "哑铃划船",
                "aliases": ["单臂哑铃划船"],
                "equipment": "dumbbell",
                "primary_muscles": ["back"],
                "is_custom": False,
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_limit", "expected_limit"),
    [(-5, 1), (100, 20)],
)
async def test_search_exercises_clamps_result_limit(
    requested_limit: int,
    expected_limit: int,
) -> None:
    service = make_exercises_service()
    service.list_exercises.return_value = ExerciseListResult(
        items=[],
        total=0,
        page=1,
        page_size=expected_limit,
        has_more=False,
    )
    exercise_tool = build_exercise_tool(
        user_id=uuid4(),
        exercises_service=service,
    )

    await exercise_tool.ainvoke({"limit": requested_limit})

    assert service.list_exercises.await_args.kwargs["page_size"] == expected_limit


def test_search_exercises_does_not_expose_user_id_to_model() -> None:
    exercise_tool = build_exercise_tool(
        user_id=uuid4(),
        exercises_service=make_exercises_service(),
    )

    properties = exercise_tool.args_schema.model_json_schema()["properties"]
    assert set(properties) == {"keyword", "equipment", "muscle", "limit"}
    assert "user_id" not in properties
