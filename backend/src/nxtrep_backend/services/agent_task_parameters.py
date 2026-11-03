"""Validate model-extracted slots before merging them into durable task state."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nxtrep_backend.schemas.agent_task import NUMERIC_FIELDS, clean_parameters


def remaining_draft_fields(
    task_type: str,
    fields: list[str],
    parameters: dict,
    entities: dict,
    *,
    invalid_fields: list[str] | tuple[str, ...] = (),
    food_catalog_actions: list[str] | tuple[str, ...] = (),
    required_context: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Resolve estimable gaps for food questions and new foods/meals with a name.

    Required tool arguments still have to pass the existing gateway and service
    validation. This only lets the planner prepare a reviewable estimate first.
    """
    remaining = list(dict.fromkeys([*fields, *invalid_fields]))[:20]
    new_meal = task_type == "nutrition_record_draft"
    new_food = task_type == "food_catalog_draft" and set(food_catalog_actions) == {"create"}
    food_question = task_type in {"general_question", "knowledge_retrieval"} and not (
        set(required_context) - {"nutrition", "exercise", "constraints"}
    )
    if not (new_meal or new_food or food_question) or any(
        entities.get(key) for key in ("entry_id", "meal_id", "confirmation_id", "food_id")
    ):
        return remaining

    items = parameters.get("items")
    items = items if isinstance(items, list) else []
    names = [parameters.get("food_name") or parameters.get("name")]
    names.extend(
        item.get("food_name") or item.get("name") for item in items if isinstance(item, dict)
    )
    if not any(isinstance(name, str) and name.strip() for name in names):
        return remaining

    invalid = set(invalid_fields)
    if "_amount_g_input" in parameters:
        hint = parameters["_amount_g_input"]
        portion_text = isinstance(hint, str) and re.fullmatch(
            r"(?:正常|普通|约|大约|大概)?\s*"
            r"(?:[一二两三四五六七八九十百]+|[1-9]\d*(?:\.\d+)?|0\.\d*[1-9]\d*|半)?\s*"
            r"(?:大|小)?(?:盒|碗|份|个|颗|片|勺|杯|块|袋|盘|条)(?:左右|装)?",
            hint.strip(),
        )
        if hint is None or hint == "" or portion_text:
            invalid.discard("amount_g")
    # A qualitative portion ("一盒") is estimable; a supplied negative, zero,
    # non-finite or boolean number is an error, not permission to invent a value.
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        value = item.get("amount_g")
        if value is None or value == "":
            continue
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            if not isinstance(value, str) or str(value).casefold() in {"nan", "inf", "infinity"}:
                invalid.add(f"items[{index}].amount_g")
        else:
            if (
                not number.is_finite()
                or not Decimal("0.001") <= number <= Decimal("99999.999")
                or number.as_tuple().exponent < -3
            ):
                invalid.add(f"items[{index}].amount_g")

    estimable = {
        "amount_g",
        "basis_amount_g",
        "portion",
        "portion_size",
        "serving_size",
        "quantity",
        "kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        "nutrients",
        "nutrition",
    }

    resolved_names = set()
    if isinstance(names[0], str) and names[0].strip():
        resolved_names.update({"food_name", "name"})
    if items and all(
        isinstance(item, dict)
        and isinstance(item.get("food_name") or item.get("name"), str)
        and (item.get("food_name") or item.get("name")).strip()
        for item in items
    ):
        resolved_names.update({"food_name", "items.food_name", "items.name"})

    def is_estimable(field: str) -> bool:
        path = re.sub(r"\[(?:\d*)\]", "", field)
        return (
            path in resolved_names
            or path in estimable
            or path in {f"items.{name}" for name in estimable}
        )

    return list(
        dict.fromkeys(
            [
                *[field for field in remaining if field in invalid or not is_estimable(field)],
                *sorted(invalid),
            ]
        )
    )[:20]


_DATE_NUMBER = r"[0-9零〇一二两三四五六七八九十]{1,4}"
_MEAL_DATE = re.compile(
    rf"\d{{4}}-\d{{2}}-\d{{2}}|(?:{_DATE_NUMBER}年)?"
    rf"(?:{_DATE_NUMBER}月)?{_DATE_NUMBER}[日号]|今天|今日|昨天|昨日|前天|前一天|前一日"
)


def _date_number(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = dict(zip(
        "零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9), strict=True
    ))
    if "十" in text:
        tens, ones = text.split("十")
        return (digits[tens] if tens else 1) * 10 + (digits[ones] if ones else 0)
    return int("".join(str(digits[c]) for c in text))


def ground_meal_date_parameters(
    message: str, parameters: dict, previous: dict, *,
    timezone: str | None = None, occurred_at: datetime | None = None,
) -> dict:
    """Ground explicit meal dates and linked meal types for an already routed action.

    Applies only to an already routed date correction. It cannot create an action,
    select a business ID, or approve a draft from arbitrary chat text.
    """
    if parameters.get("action", previous.get("action")) != "change_date":
        return parameters
    matches = list(_MEAL_DATE.finditer(message))
    if not matches:
        return parameters
    try:
        zone = ZoneInfo(timezone or "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Shanghai")
    today = (occurred_at or datetime.now(zone)).astimezone(zone).date()

    def resolve(text, source=None):
        if text in {"前一天", "前一日"}:
            try:
                return (date.fromisoformat(source) - timedelta(days=1)).isoformat()
            except (ValueError, TypeError):
                return text
        relative = {"今天": 0, "今日": 0, "昨天": -1, "昨日": -1, "前天": -2}
        if text in relative:
            return (today + timedelta(days=relative[text])).isoformat()
        parts = re.fullmatch(
            rf"(?:(?P<year>{_DATE_NUMBER})年)?(?:(?P<month>{_DATE_NUMBER})月)?"
            rf"(?P<day>{_DATE_NUMBER})[日号]", text,
        )
        if parts:
            try:
                return date(
                    _date_number(parts["year"]) if parts["year"] else today.year,
                    _date_number(parts["month"]) if parts["month"] else today.month,
                    _date_number(parts["day"]),
                ).isoformat()
            except (ValueError, KeyError):
                return text  # normal validation reports an invalid date; never roll it over
        return text

    result = dict(parameters)
    connector = r"改|挪|移|应[该当]?是|实际是|其实是|本来是"
    if len(matches) == 2 and re.search(connector, message[matches[0].end():matches[1].start()]):
        source = resolve(matches[0].group())
        result.update(source_date=source, target_date=resolve(matches[1].group(), source))
    elif len(matches) == 1:
        before = message[:matches[0].start()]
        known_source = previous.get("source_date") or result.get("source_date")
        if re.search(connector, before) or matches[0].group() in {"前一天", "前一日"}:
            result["target_date"] = resolve(matches[0].group(), known_source)
            if previous.get("source_date"):
                result["source_date"] = previous["source_date"]
        elif not previous.get("source_date"):
            result["source_date"] = resolve(matches[0].group())
        elif not previous.get("target_date"):
            result["target_date"] = resolve(matches[0].group(), known_source)
    # Keep an explicit linked list of meal types narrower than a whole-day move.
    # Exclusions and separate requests remain with semantic routing.
    action = re.search(connector, message)
    scope_text = message[:action.start()] if action else ""
    meal_names = r"早餐|早饭|午餐|午饭|晚餐|晚饭|加餐"
    if (
        re.search(rf"(?:{meal_names})(?:和|、|以及)(?:{meal_names})", scope_text)
        and not re.search(r"不要|别|保留|不动|不改|不挪|不移|不是", scope_text)
        and not re.search(r"整天|一天的饮食|全部饮食|所有饮食", scope_text)
    ):
        result.update(scope="meals", meal_types=[
            kind for pattern, kind in (
                (r"早餐|早饭", "breakfast"), (r"午餐|午饭", "lunch"),
                (r"晚餐|晚饭", "dinner"), (r"加餐", "snack"),
            ) if re.search(pattern, scope_text)
        ])
        result.pop("meal_type", None)
    return result


def normalize_task_parameters(
    parameters: dict,
    *,
    timezone: str | None = None,
    occurred_at: datetime | None = None,
    task_type: str | None = None,
) -> tuple[dict, list[str]]:
    valid = clean_parameters(parameters)
    invalid = [key for key in parameters if key in NUMERIC_FIELDS and key not in valid]
    if task_type == "workout_record_draft" and "reps" in valid and not 1 <= valid["reps"] <= 100:
        valid.pop("reps")
        invalid.append("reps")
    try:
        zone = ZoneInfo(timezone or "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Asia/Shanghai")
    today = (occurred_at or datetime.now(zone)).astimezone(zone).date()
    for key in ("workout_date", "date", "source_date", "target_date"):
        if key not in valid:
            continue
        value = str(valid[key]).strip()
        relative = {
            "今天": 0,
            "今日": 0,
            "today": 0,
            "昨天": -1,
            "昨日": -1,
            "yesterday": -1,
            "前天": -2,
        }
        if key == "target_date" and value in {"前一天", "前一日"} and valid.get("source_date"):
            try:
                valid[key] = (
                    date.fromisoformat(str(valid["source_date"])) - timedelta(days=1)
                ).isoformat()
            except ValueError:
                valid.pop(key)
                invalid.append(key)
        elif value.casefold() in relative:
            valid[key] = (today + timedelta(days=relative[value.casefold()])).isoformat()
        else:
            try:
                valid[key] = date.fromisoformat(value).isoformat()
            except ValueError:
                valid.pop(key)
                invalid.append(key)
        if (
            key in valid
            and task_type == "workout_record_draft"
            and date.fromisoformat(valid[key]) > today
        ):
            valid.pop(key)
            invalid.append(key)
    return valid, invalid
