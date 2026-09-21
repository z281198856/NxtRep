from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from nxtrep_backend.schemas.agent import AgentExecutionBundle

MAX_EXERCISES_IN_ANSWER = 8


def direct_today_training_answer(
    execution_bundle: AgentExecutionBundle,
) -> str | None:
    """Render the local today-training query without another model round trip."""
    if len(execution_bundle.branch_results) != 1:
        return None

    branch = execution_bundle.branch_results[0]
    if (
        branch.task_type != "structured_data_query"
        or branch.status != "completed"
        or branch.result is None
        or branch.result.get("query_kind") != "today_training"
    ):
        return None

    result = branch.result
    active_workout = _mapping(result.get("active_workout"))
    if active_workout is not None:
        return _active_workout_answer(active_workout)

    events = [
        event
        for value in _list(result.get("scheduled_events"))
        if (event := _mapping(value)) is not None
    ]
    if events:
        return _scheduled_events_answer(events)

    active_plan = _mapping(result.get("active_plan"))
    if active_plan is not None:
        return _active_plan_answer(active_plan)

    return (
        "你今天还没有进行中的训练，也没有今日安排或已启用的训练计划。\n"
        "可以先创建训练计划；如果想马上练，也可以让我按“徒手”或“健身房器械”"
        "帮你生成一节训练。"
    )


def _active_workout_answer(workout: Mapping[str, object]) -> str:
    status = _text(workout.get("status"))
    state_text = "暂停中" if status == "paused" else "进行中"
    lines = [f"你有一场{state_text}的训练，优先继续完成这一节。"]
    exercise_lines = _exercise_lines(workout.get("exercises"), active=True)
    if exercise_lines:
        lines.append("当前进度：")
        lines.extend(f"- {line}" for line in exercise_lines)
        lines.append("按剩余组数继续即可；如果出现明显疼痛，请立即停止并调整。")
    else:
        lines.append("这节训练目前没有可显示的动作，请返回训练页检查训练内容。")
    return "\n".join(lines)


def _scheduled_events_answer(events: list[Mapping[str, object]]) -> str:
    if len(events) == 1:
        event = events[0]
        status = _text(event.get("status")) or "planned"
        title = _text(event.get("title")) or "训练"
        duration = _positive_int(event.get("estimated_minutes"))
        duration_text = f"（约 {duration} 分钟）" if duration is not None else ""
        status_intro = {
            "completed": f"你今天的「{title}」已经完成。",
            "missed": f"你今天安排了「{title}」{duration_text}，目前已标记为错过。",
            "skipped": f"你今天的「{title}」已跳过。",
        }
        lines = [status_intro.get(status, f"你今天安排了「{title}」{duration_text}。")]
    else:
        lines = ["你今天有这些训练安排："]
        for event in events:
            title = _text(event.get("title")) or "训练"
            duration = _positive_int(event.get("estimated_minutes"))
            duration_text = f"，约 {duration} 分钟" if duration is not None else ""
            status_text = {
                "planned": "待训练",
                "completed": "已完成",
                "missed": "已错过",
                "skipped": "已跳过",
            }.get(_text(event.get("status")), "待训练")
            lines.append(f"- {title}（{status_text}{duration_text}）")

    planned_event = next(
        (event for event in events if _text(event.get("status")) == "planned"),
        None,
    )
    if planned_event is not None:
        content = _mapping(planned_event.get("content"))
        exercise_values = content.get("exercises") if content is not None else None
        exercise_lines = _exercise_lines(exercise_values, active=False)
        if exercise_lines:
            lines.append("训练内容：")
            lines.extend(f"- {line}" for line in exercise_lines)
        else:
            exercise_count = len(_list(exercise_values))
            if exercise_count:
                lines.append(f"计划包含 {exercise_count} 个动作，进入训练页可查看每组目标。")
        lines.append("按计划热身后开始；如果出现明显疼痛，请停止训练。")
    elif any(_text(event.get("status")) == "completed" for event in events):
        lines.append("今天的安排已完成，接下来以放松和恢复为主。")
    elif any(_text(event.get("status")) == "missed" for event in events):
        lines.append("如需补练，建议先重新安排，避免为了补课临时堆高训练量。")

    return "\n".join(lines)


def _active_plan_answer(plan: Mapping[str, object]) -> str:
    name = _text(plan.get("name")) or "当前计划"
    frequency = _positive_int(plan.get("weekly_frequency"))
    frequency_text = f"，每周 {frequency} 练" if frequency is not None else ""
    lines = [f"你已启用「{name}」{frequency_text}，但今天没有排定训练。"]

    day_names = []
    for value in _list(plan.get("days")):
        day = _mapping(value)
        if day is not None and (day_name := _text(day.get("name"))):
            day_names.append(day_name)
    if day_names:
        lines.append(f"计划日包括：{'、'.join(day_names[:MAX_EXERCISES_IN_ANSWER])}。")
    lines.append("如果今天状态良好并想加练，可从计划中选择一个训练日；否则按恢复日安排。")
    return "\n".join(lines)


def _exercise_lines(value: object, *, active: bool) -> list[str]:
    exercise_values = _list(value)
    lines: list[str] = []
    for item_value in exercise_values:
        item = _mapping(item_value)
        if item is None:
            continue
        name = (
            _text(item.get("name"))
            or _text(item.get("name_zh"))
            or _text(item.get("exercise_name"))
        )
        if name is None:
            continue
        target = _mapping(item.get("target")) if active else item
        target = target or {}
        lines.append(_exercise_line(name, item, target, active=active))
        if len(lines) == MAX_EXERCISES_IN_ANSWER:
            break

    hidden_count = len(exercise_values) - len(lines)
    if hidden_count > 0 and len(lines) == MAX_EXERCISES_IN_ANSWER:
        lines.append(f"另有 {hidden_count} 个动作，请在训练页查看")
    return lines


def _exercise_line(
    name: str,
    item: Mapping[str, object],
    target: Mapping[str, object],
    *,
    active: bool,
) -> str:
    if target.get("skipped") is True:
        return f"{name}：已跳过"

    target_sets = _positive_int(target.get("sets")) or _positive_int(
        target.get("target_sets")
    )
    completed_sets = _non_negative_int(item.get("completed_sets")) if active else None
    details: list[str] = []
    if active and completed_sets is not None:
        if target_sets is not None:
            details.append(f"已完成 {completed_sets}/{target_sets} 组")
        else:
            details.append(f"已完成 {completed_sets} 组")
    elif target_sets is not None:
        details.append(f"{target_sets} 组")

    rep_min = _positive_int(target.get("rep_min"))
    rep_max = _positive_int(target.get("rep_max"))
    if rep_min is not None and rep_max is not None:
        rep_text = str(rep_min) if rep_min == rep_max else f"{rep_min}–{rep_max}"
        details.append(f"每组 {rep_text} 次")
    elif rep_min is not None:
        details.append(f"每组 {rep_min} 次")

    load = _number_text(target.get("target_load_kg"))
    if load is not None:
        details.append(f"目标 {load} kg")
    rir = _non_negative_int(target.get("target_rir"))
    if rir is not None:
        details.append(f"RIR {rir}")

    return f"{name}：{'，'.join(details)}" if details else name


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _positive_int(value: object) -> int | None:
    number = _non_negative_int(value)
    return number if number is not None and number > 0 else None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _number_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), "f")
