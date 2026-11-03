"""Bound model context while retaining durable chat history unchanged."""

import json
import re
from dataclasses import asdict, is_dataclass, replace
from math import isfinite
from typing import Any

from pydantic import BaseModel

MAX_CONTEXT_CHARS = 24_000
_PRIORITY_KEYS = (
    "schema_version",
    "active_task",
    "suspended_task",
    "suspended_tasks",
    "task_id",
    "task_type",
    "status",
    "current_step",
    "entities",
    "reference_entities",
    "parameters",
    "missing_fields",
    "candidates",
    "last_tool_call",
    "last_tool_result",
    "confirmation_id",
    "entry_id",
    "workout_id",
    "workout_exercise_id",
    "exercise_id",
    "set_id",
    "item_index",
    "operation_type",
    "version",
    "success",
    "data",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _fit(value: Any, budget: int, depth: int = 0) -> Any:
    value = _plain(value)
    if depth > 6:
        return None
    if isinstance(value, str):
        if len(_json(value)) <= budget:
            return value
        low, high = 0, min(len(value), max(0, budget - 2))
        while low < high:
            mid = (low + high + 1) // 2
            if len(_json(value[:mid] + "…")) <= budget:
                low = mid
            else:
                high = mid - 1
        return value[:low] + "…" if budget >= 3 else ""
    if isinstance(value, dict):
        result = {}
        keys = sorted(
            value,
            key=lambda key: (
                _PRIORITY_KEYS.index(key) if key in _PRIORITY_KEYS else len(_PRIORITY_KEYS),
            ),
        )
        for key in keys[:40]:
            if not isinstance(key, str):
                continue
            remaining = budget - len(_json(result)) - len(_json(key)) - 2
            if remaining < 4:
                continue
            result[key] = _fit(value[key], remaining, depth + 1)
            if len(_json(result)) > budget:
                result.pop(key)
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value[:24]:
            remaining = budget - len(_json(result)) - 1
            if remaining < 4:
                break
            result.append(_fit(item, remaining, depth + 1))
            if len(_json(result)) > budget:
                result.pop()
        return result
    if value is None or isinstance(value, (bool, int)):
        return value if len(_json(value)) <= budget else None
    if isinstance(value, float):
        return value if isfinite(value) and len(_json(value)) <= budget else None
    return _fit(str(value), budget, depth + 1)


def bound_payload(value: Any, limit: int = 4_000) -> Any:
    """Return valid JSON data under a character budget, prioritising stable task IDs.

    The result is a context projection, never a replacement for storage or tool
    arguments. Character budgets are explicit; they are not claimed to be tokens.
    """
    if limit < 32:
        raise ValueError("context payload limit must be at least 32 characters")
    return _fit(value, limit)


def _message_dict(message: Any) -> dict:
    if isinstance(message, dict):
        return {"role": message.get("role", "user"), "content": str(message.get("content", ""))}
    return {"role": message.role, "content": str(message.content)}


def _keywords(task_state: dict, current_message: str) -> list[str]:
    task = task_state.get("active_task") or task_state.get("suspended_task") or {}
    result = [str(value) for value in task.get("entities", {}).values() if isinstance(value, str)]
    result += [
        str(task.get("parameters", {}).get(name, ""))
        for name in ("exercise_name", "food_name", "meal_type")
    ]
    result += re.findall(r"[A-Za-z_]{3,}|[\u4e00-\u9fff]{2,8}", current_message)
    return [word.casefold() for word in result if len(word) >= 2][:20]


def bound_conversation(context: Any, current_message: str = "", limit: int = MAX_CONTEXT_CHARS):
    """Project the existing conversation dataclass/dict without mutating history.

    Task state is reserved first. Keep the last four chat messages and up to eight
    earlier related messages. Storage messages contain user/assistant text only;
    transient tool-call histories can use ``bound_messages`` below.
    """
    if limit < 512:
        raise ValueError("conversation context limit must be at least 512 characters")
    get = (
        context.get
        if isinstance(context, dict)
        else lambda name, default: getattr(context, name, default)
    )
    task_state = bound_payload(get("task_state", {}), min(6_000, max(32, limit // 3)))
    meal_cards = bound_payload(list(get("meal_confirmations", ())), min(3_500, max(32, limit // 5)))
    summary = bound_payload(get("summary", None), min(3_500, max(32, limit // 5)))
    input_hints = bound_payload(get("input_hints", {}), min(2000, max(32, limit // 8)))
    original = list(get("recent_messages", ()))
    keywords = _keywords(task_state, current_message)
    message_dicts = [_message_dict(message) for message in original]
    mandatory = set(range(max(0, len(original) - 4), len(original)))
    relevant = [
        index
        for index in range(max(0, len(original) - 4))
        if any(word in message_dicts[index]["content"].casefold() for word in keywords)
    ]
    chosen = sorted(mandatory | set(relevant[-8:]))
    envelope = {
        "task_state": task_state,
        "meal_confirmations": meal_cards,
        "summary": summary,
        "recent_messages": [],
        **({"input_hints": input_hints} if input_hints else {}),
    }
    remaining = max(0, limit - len(_json(envelope)) - 128)
    selected = []
    # Newest facts take priority when a single historical answer is very long.
    for index in reversed(chosen):
        message = message_dicts[index]
        if remaining < 64:
            break
        allocation = min(4_000, remaining)
        message = bound_payload(message, allocation)
        if not message.get("content"):
            continue
        remaining -= len(_json(message)) + 1
        item = original[index]
        selected.append(
            replace(item, content=message["content"]) if is_dataclass(item) else message
        )
    selected.reverse()
    updates = {
        "task_state": task_state,
        "meal_confirmations": tuple(meal_cards),
        "summary": summary,
        "recent_messages": tuple(selected),
        **({"input_hints": input_hints} if input_hints else {}),
    }
    if isinstance(context, dict):
        return {**context, **updates}
    if is_dataclass(context):
        return replace(context, **updates)
    if isinstance(context, BaseModel):
        return context.model_copy(update=updates)
    raise TypeError("expected an existing conversation dataclass, model, or dict")


def bound_messages(messages: list[Any], limit: int = MAX_CONTEXT_CHARS) -> list[Any]:
    """Trim transient model messages as complete tool-call/result blocks.

    Orphan ToolMessages and incomplete historical call blocks are omitted. Tool
    arguments and results within retained blocks remain byte-for-byte unchanged.
    """
    blocks = []
    index = 0
    while index < len(messages):
        message = messages[index]
        raw = _plain(message)
        if not isinstance(raw, dict):
            index += 1
            continue
        calls = raw.get("tool_calls") or []
        role = raw.get("role") or raw.get("type")
        if role == "tool":
            index += 1
            continue
        if calls:
            expected = {str(call.get("id")) for call in calls if call.get("id")}
            group = [message]
            cursor = index + 1
            found = set()
            while cursor < len(messages):
                tool = _plain(messages[cursor])
                if not isinstance(tool, dict) or (tool.get("role") or tool.get("type")) != "tool":
                    break
                if str(tool.get("tool_call_id")) in expected:
                    group.append(messages[cursor])
                    found.add(str(tool.get("tool_call_id")))
                cursor += 1
            if expected and found == expected:
                blocks.append(group)
            index = cursor
        else:
            blocks.append([message])
            index += 1
    selected, remaining = [], limit
    for block in reversed(blocks):
        cost = sum(len(_json(_plain(message))) + 1 for message in block)
        if cost <= remaining:
            selected.append(block)
            remaining -= cost
    return [message for block in reversed(selected) for message in block]
