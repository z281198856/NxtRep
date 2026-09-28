from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from nxtrep_backend.api.routes.training import get_active_plan


@pytest.mark.asyncio
async def test_active_plan_response_includes_visible_exercise_names() -> None:
    user_id = uuid4()
    exercise_id = uuid4()
    plan = SimpleNamespace(
        id=uuid4(),
        plan_id=uuid4(),
        name="三日力量计划",
        version=1,
        weekly_frequency=3,
        activated_at=datetime.now(UTC),
        days=[
            {
                "id": str(uuid4()),
                "day_index": 1,
                "name": "全身 A",
                "estimated_minutes": 45,
                "exercises": [
                    {
                        "exercise_id": str(exercise_id),
                        "target_sets": 3,
                        "rep_min": 8,
                        "rep_max": 10,
                    }
                ],
            }
        ],
    )
    repository = MagicMock()
    repository.get_active_plan = AsyncMock(return_value=plan)
    repository.plan_exercise_names = AsyncMock(return_value={str(exercise_id): "哑铃卧推"})
    with patch(
        "nxtrep_backend.api.routes.training.SqlAlchemyTrainingRepository",
        return_value=repository,
    ):
        response = await get_active_plan(SimpleNamespace(id=user_id), MagicMock())

    assert response.days[0]["exercises"][0]["exercise_name"] == "哑铃卧推"
    assert "exercise_name" not in plan.days[0]["exercises"][0]
    repository.plan_exercise_names.assert_awaited_once_with(user_id, {exercise_id})
