"""Read-only coaching facts and evidence over explicit, comparable periods."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from nxtrep_backend.services.body import BodyService


async def build_progress_review(
    body_service: BodyService,
    user_id: UUID,
    start_date: date,
    end_date: date,
) -> dict:
    days = (end_date - start_date).days + 1
    if not 1 <= days <= 365:
        raise ValueError("复盘日期须为不超过一年内的连续区间")
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    current = await body_service.overview(user_id, start_date, end_date)
    previous = await body_service.overview(user_id, previous_start, previous_end)
    weight = await body_service.body_trend(user_id, "weight", start_date, end_date, "raw")
    waist = await body_service.body_trend(user_id, "waist", start_date, end_date, "raw")
    recovery = await body_service.recovery(user_id, start_date, end_date)
    actions = []
    missing = []
    training = current["training"]
    nutrition = current["nutrition"]
    if training["workout_count"] == 0:
        missing.append("training")
        actions.append("本期没有训练记录，先核对是否漏记，再决定是否调整安排。")
    elif Decimal(training["completion_rate"]) < Decimal("0.8"):
        actions.append(
            f"本期日历完成率为 {Decimal(training['completion_rate']) * 100:.0f}%，"
            "先核对未完成安排；需要改期时再生成待确认草稿。"
        )
    elif training["workout_count"] > previous["training"]["workout_count"]:
        actions.append("本期训练记录比前一期更多，下一阶段先维持可持续频率，再结合恢复决定递增。")
    else:
        actions.append("训练记录已有连续性，下一阶段优先维持安排，并核对动作完成质量。")
    completeness = Decimal(nutrition["record_completeness"])
    if completeness < Decimal("0.7"):
        missing.append("nutrition")
        actions.append(
            f"本期有饮食记录的日期约占 {completeness * 100:.0f}%，"
            "先补齐记录；记录均值不能当作实际全天摄入来调整热量。"
        )
    else:
        actions.append("饮食记录覆盖较多日期，仍需核对餐次是否完整，再结合已有目标调整份量。")
    if len(weight) < 2:
        missing.append("body")
        actions.append("本期体重测量不足两次，先在相似条件下补充测量，暂不判断变化趋势。")
    else:
        change = current["body"].get("smoothed_change_kg")
        actions.append(
            f"本期平滑体重变化为 {change} kg，结合目标、腰围和训练表现观察；"
            "不要仅凭一次称重修改计划。"
        )
    if any(point.get("pain_flags", 0) for point in recovery.get("points", [])):
        actions[-1] = "本期存在疼痛记录，先核对目前恢复状态，暂停直接加重并按情况寻求专业帮助。"
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "current": current,
        "previous_period": {
            "start_date": previous_start.isoformat(),
            "end_date": previous_end.isoformat(),
        },
        "previous": previous,
        "training_count_change": training["workout_count"] - previous["training"]["workout_count"],
        "weight_points": weight,
        "waist_points": waist,
        "recovery": recovery,
        "recommendations": actions[:3],
        "missing_data": missing,
        "evidence": [
            {
                "type": "user_records",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            {
                "type": "comparison_records",
                "start_date": previous_start.isoformat(),
                "end_date": previous_end.isoformat(),
            },
        ],
        "limitations": [
            "只反映已保存记录；缺记录不等于未训练或未进食。",
            "阶段之间的变化是观察结果，不能据此断言因果关系。",
        ],
    }
