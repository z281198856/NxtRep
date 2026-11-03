import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage

from nxtrep_backend.agents.tools.training import build_training_draft_tools
from nxtrep_backend.services.agent_handlers.general import GeneralQuestionBranchHandler
from nxtrep_backend.services.body import BodyService
from nxtrep_backend.services.coaching_review import build_progress_review
from nxtrep_backend.services.platform import PlatformConflictError, PlatformService


@pytest.mark.asyncio
async def test_report_rejects_excessive_period_before_querying_records():
    repository = MagicMock()
    with pytest.raises(PlatformConflictError, match="365"):
        await PlatformService(repository).generate_report(
            uuid4(), "phase", date(2025, 1, 1), date(2026, 1, 1)
        )
    repository.list_reports.assert_not_called()


@pytest.mark.asyncio
async def test_review_compares_equal_periods_and_does_not_invent_missing_records():
    service = MagicMock()
    current = {
        "training": {"workout_count": 0, "completion_rate": "0"},
        "nutrition": {"record_completeness": "0"},
        "body": {},
    }
    prior = {**current, "training": {"workout_count": 2, "completion_rate": "1"}}
    service.overview = AsyncMock(side_effect=[current, prior])
    service.body_trend = AsyncMock(return_value=[])
    service.recovery = AsyncMock(return_value={"points": []})
    user = uuid4()
    result = await build_progress_review(service, user, date(2026, 10, 1), date(2026, 10, 7))
    assert result["previous_period"] == {"start_date": "2026-09-24", "end_date": "2026-09-30"}
    assert result["training_count_change"] == -2
    assert result["missing_data"] == ["training", "nutrition", "body"]
    assert len(result["recommendations"]) == 3
    assert "漏记" in result["recommendations"][0]
    assert "未进食" in result["limitations"][0]
    service.overview.assert_any_await(user, date(2026, 9, 24), date(2026, 9, 30))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["empty", "old_fatigue", "pain", "today_low"])
async def test_recovery_separates_missing_today_from_previous_records(kind):
    repository = MagicMock()
    today = datetime.now(UTC).date()
    row = SimpleNamespace(
        started_at=datetime.now(UTC) - timedelta(days=1), pre_check={}, fatigue=4, pain=[]
    )
    if kind == "pain":
        row.pain = [{"location": "knee"}]
    if kind == "today_low":
        row.started_at = datetime.now(UTC)
        row.pre_check = {"sleep_quality": 1, "energy": 2}
        row.fatigue = None
    repository.progress_rows = AsyncMock(
        return_value=([] if kind == "empty" else [row], [], [], [], [])
    )
    result = await BodyService(repository, MagicMock()).recovery_status(uuid4(), today)
    assert (
        result["suggested_handling"]
        == {
            "empty": "insufficient_data",
            "old_fatigue": "consider_lighter",
            "pain": "review_pain",
            "today_low": "consider_lighter",
        }[kind]
    )
    if kind != "today_low":
        assert result["today_check"] is None
        assert "sleep_quality" in result["missing_fields"]


@pytest.mark.asyncio
async def test_pain_blocks_compression_and_creates_no_confirmation():
    training = MagicMock()
    training.repository.get_calendar_event = AsyncMock(
        return_value=SimpleNamespace(scheduled_date=date.today())
    )
    training.create_compression_draft = AsyncMock()
    training.submit_reschedule = AsyncMock()
    body = MagicMock()
    body.recovery_status = AsyncMock(return_value={"pain_records": ["knee"]})
    context = SimpleNamespace(user_id=uuid4(), training_service=training, body_service=body)
    tool = next(
        t for t in build_training_draft_tools(context) if t.name == "propose_recovery_adjustment"
    )
    result = await tool.ainvoke(
        {"event_id": str(uuid4()), "target_minutes": 30, "reason": "恢复不好"}
    )
    assert result["status"] == "needs_review"
    training.create_compression_draft.assert_not_awaited()
    training.submit_reschedule.assert_not_awaited()


def test_secondary_read_retry_cannot_hide_calculated_meal():
    message = ToolMessage(
        name="calculate_meal_option",
        tool_call_id="meal",
        content=json.dumps(
            {
                "status": "available",
                "saved": False,
                "items": [{"name": "熟米饭", "amount_g": "150"}],
                "meal_totals": {"kcal": "180", "protein_g": "4", "carbs_g": "40", "fat_g": "1"},
                "summary": {"target": None},
            }
        ),
    )
    answer = GeneralQuestionBranchHandler._retain_meal_option("目前仅一条体重记录。", [message])
    assert "熟米饭约150克" in answer
    assert "180千卡" in answer and "没有写入饮食记录" in answer
    assert "仅一条体重记录" in answer
