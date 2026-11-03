"""Shared local notification timing; no scheduler or startup service."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo


def coach_paused(config: dict | None, now: datetime) -> bool:
    value = (config or {}).get("pause_until")
    return bool(value and datetime.fromisoformat(value) > now)


def coach_quiet(config: dict | None, now: datetime) -> bool:
    config = config or {}
    if not config.get("enabled", False):
        return False
    local = now.astimezone(ZoneInfo(config.get("timezone", "Asia/Shanghai"))).time()
    start = time.fromisoformat(config["start"])
    end = time.fromisoformat(config["end"])
    return start <= local < end if start < end else local >= start or local < end


def notice_due(data: dict, now: datetime | None = None) -> bool:
    value = data.get("snoozed_until")
    return not value or datetime.fromisoformat(value) <= (now or datetime.now(UTC))
