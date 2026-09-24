"""Parse a small, explicit training-table notation into plan snapshots."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID


class TrainingTextParseError(RuntimeError):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"第 {line} 行：{message}")
        self.line = line


DAY_RE = re.compile(
    r"^(?:周|星期)(?P<weekday>[一二三四五六日天])\s*[：:]\s*(?P<rest>.*)$"
    r"|^(?:第\s*(?P<ordinal>[1-7])\s*天|Day\s*(?P<day>[1-7]))\s*[：:]\s*(?P<rest_en>.*)$",
    re.IGNORECASE,
)
EXERCISE_RE = re.compile(
    r"^(?P<name>.+?)\s*(?P<sets>\d{1,2})\s*"
    r"(?:组\s*[×x*]?|[×x*])\s*"
    r"(?P<min>\d{1,3})(?:\s*[-~–至到]\s*(?P<max>\d{1,3}))?\s*次?$",
    re.IGNORECASE,
)
WEEKDAYS = {day: index for index, day in enumerate("一二三四五六日", 1)}
WEEKDAYS["天"] = 7


def normalize_name(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def parse_training_text(
    text: str,
    exercise_names: Iterable[tuple[UUID, str, str | None]],
) -> list[dict]:
    """Require explicit sets/reps and exact catalog name or unambiguous alias."""
    canonical: dict[str, dict[UUID, str]] = defaultdict(dict)
    aliases: dict[str, dict[UUID, str]] = defaultdict(dict)
    for exercise_id, name, alias in exercise_names:
        canonical[normalize_name(name)][exercise_id] = name
        if alias:
            aliases[normalize_name(alias)][exercise_id] = name

    days: dict[int, dict] = {}
    current_day: int | None = None
    saw_heading = False
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        heading = DAY_RE.fullmatch(line)
        if heading:
            saw_heading = True
            weekday = heading.group("weekday")
            current_day = (
                WEEKDAYS[weekday]
                if weekday
                else int(heading.group("ordinal") or heading.group("day"))
            )
            if current_day in days:
                raise TrainingTextParseError(line_no, "同一天出现了两次，请合并动作")
            days[current_day] = {
                "day_index": current_day,
                "name": f"周{'日' if weekday == '天' else weekday}训练"
                if weekday
                else f"第 {current_day} 天训练",
                "exercises": [],
            }
            line = heading.group("rest") or heading.group("rest_en") or ""
        elif current_day is None:
            if saw_heading:
                raise TrainingTextParseError(line_no, "请先写训练日标题")
            current_day = 1
            days[current_day] = {"day_index": 1, "name": "第 1 天训练", "exercises": []}

        for part in re.split(r"[，,；;]", line):
            part = re.sub(r"^(?:[-•]\s*|\d+[.、]\s*)", "", part.strip())
            if not part:
                continue
            match = EXERCISE_RE.fullmatch(part)
            if not match:
                raise TrainingTextParseError(
                    line_no, f"无法识别“{part}”，请写成“动作名 3×8”或“动作名 3×8-12”"
                )
            raw_name = match.group("name").strip()
            key = normalize_name(raw_name)
            matches = canonical.get(key) or aliases.get(key, {})
            if not matches:
                raise TrainingTextParseError(
                    line_no, f"动作库中找不到“{raw_name}”，请使用完整动作名称"
                )
            if len(matches) > 1:
                choices = "、".join(sorted(set(matches.values()))[:5])
                raise TrainingTextParseError(
                    line_no, f"“{raw_name}”对应多个动作：{choices}；请写全名"
                )
            sets = int(match.group("sets"))
            rep_min = int(match.group("min"))
            rep_max = int(match.group("max") or rep_min)
            if not 1 <= sets <= 20 or not 1 <= rep_min <= rep_max <= 100:
                raise TrainingTextParseError(
                    line_no, "组数须为 1–20，次数须为 1–100 且范围从小到大"
                )
            exercise_id, name = next(iter(matches.items()))
            items = days[current_day]["exercises"]
            if len(items) >= 30:
                raise TrainingTextParseError(line_no, "单个训练日最多支持 30 个动作")
            items.append(
                {
                    "exercise_id": str(exercise_id),
                    "exercise_name": name,
                    "order_no": len(items) + 1,
                    "target_sets": sets,
                    "rep_min": rep_min,
                    "rep_max": rep_max,
                    "target_load_kg": None,
                    "target_rir": None,
                    "rest_seconds": None,
                }
            )

    if not days:
        raise TrainingTextParseError(1, "没有找到动作安排")
    for day_index, day in days.items():
        if not day["exercises"]:
            raise TrainingTextParseError(day_index, f"第 {day_index} 天没有动作")
        day["estimated_minutes"] = min(
            300, max(15, 10 + sum(item["target_sets"] * 2 for item in day["exercises"]))
        )
    return [days[index] for index in sorted(days)]
