from nxtrep_backend.agents.today_training_answer import direct_today_training_answer
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentExecutionBundle


def make_bundle(result: dict) -> AgentExecutionBundle:
    return AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="structured_data_query",
                status="completed",
                result={"query_kind": "today_training", **result},
            )
        ]
    )


def test_direct_answer_prioritizes_active_workout_progress() -> None:
    bundle = make_bundle(
        {
            "active_workout": {
                "status": "in_progress",
                "exercises": [
                    {
                        "name": "深蹲",
                        "completed_sets": 1,
                        "target": {
                            "sets": 3,
                            "rep_min": 8,
                            "rep_max": 12,
                            "target_load_kg": "40.000",
                            "target_rir": 2,
                        },
                    }
                ],
            },
            "scheduled_events": [
                {"status": "planned", "title": "不应覆盖进行中训练"}
            ],
            "active_plan": {"name": "两日计划"},
        }
    )

    answer = direct_today_training_answer(bundle)

    assert answer is not None
    assert "进行中的训练" in answer
    assert "深蹲：已完成 1/3 组，每组 8–12 次，目标 40 kg，RIR 2" in answer
    assert "不应覆盖进行中训练" not in answer


def test_direct_answer_describes_planned_event_and_exercises() -> None:
    bundle = make_bundle(
        {
            "active_workout": None,
            "scheduled_events": [
                {
                    "status": "planned",
                    "title": "上肢力量",
                    "estimated_minutes": 45,
                    "content": {
                        "exercises": [
                            {
                                "name": "卧推",
                                "target_sets": 4,
                                "rep_min": 6,
                                "rep_max": 8,
                            }
                        ]
                    },
                }
            ],
            "active_plan": {"name": "三日计划"},
        }
    )

    answer = direct_today_training_answer(bundle)

    assert answer is not None
    assert "今天安排了「上肢力量」（约 45 分钟）" in answer
    assert "卧推：4 组，每组 6–8 次" in answer


def test_direct_answer_uses_active_plan_when_today_has_no_event() -> None:
    bundle = make_bundle(
        {
            "active_workout": None,
            "scheduled_events": [],
            "active_plan": {
                "name": "两日全身计划",
                "weekly_frequency": 2,
                "days": [{"name": "全身 A"}, {"name": "全身 B"}],
            },
        }
    )

    answer = direct_today_training_answer(bundle)

    assert answer is not None
    assert "已启用「两日全身计划」，每周 2 练" in answer
    assert "今天没有排定训练" in answer
    assert "计划日包括：全身 A、全身 B" in answer


def test_direct_answer_explains_completely_empty_training_state() -> None:
    bundle = make_bundle(
        {
            "active_workout": None,
            "scheduled_events": [],
            "active_plan": None,
        }
    )

    answer = direct_today_training_answer(bundle)

    assert answer is not None
    assert "没有进行中的训练" in answer
    assert "没有今日安排或已启用的训练计划" in answer
    assert "徒手" in answer
    assert "健身房器械" in answer


def test_direct_answer_ignores_other_structured_queries() -> None:
    bundle = AgentExecutionBundle(
        branch_results=[
            AgentBranchResult(
                task_type="structured_data_query",
                status="completed",
                result={"query_kind": "recent_workouts"},
            )
        ]
    )

    assert direct_today_training_answer(bundle) is None
