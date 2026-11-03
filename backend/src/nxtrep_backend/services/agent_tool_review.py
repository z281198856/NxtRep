"""Retire a selection review only after an owned read and matching valid proposal."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from nxtrep_backend.schemas.agent import AgentConfirmationCard

_FAMILIES = {
    "meal": {
        "read": "read_saved_meal_for_change",
        "selected": "selected_entry",
        "ids": ("entry_id",),
        "proposals": {
            "propose_saved_meal_update": "nutrition_entry_update",
            "propose_saved_meal_item_remove": "nutrition_entry_update",
            "propose_saved_meal_delete": "nutrition_entry_delete",
        },
    },
    "set": {
        "read": "read_workout_set_for_change",
        "selected": "selected_set",
        "ids": ("workout_id", "set_id"),
        "proposals": {
            "propose_workout_set_update": "workout_set_update",
            "propose_workout_set_void": "workout_set_void",
        },
    },
    "record": {
        "read": "read_workout_record_for_change",
        "selected": "selected_record",
        "ids": ("workout_id", "workout_exercise_id"),
        "proposals": {
            "propose_workout_record_update": "workout_record_update",
            "propose_workout_record_void": "workout_record_void",
        },
    },
}


def _payload(content: Any) -> dict | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None


def _identifier(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _identity(value: dict, spec: dict) -> tuple[str, ...] | None:
    ids = tuple(_identifier(value.get(key)) for key in spec["ids"])
    return ids if all(ids) else None


def _same_version(selected: dict, after: dict, family: str) -> bool:
    if family != "record":
        version = selected.get("version")
        return (
            type(version) is int
            and version > 0
            and type(after.get("expected_version")) is int
            and after["expected_version"] == version
        )
    request = after.get("request")
    if not isinstance(request, dict):
        return False
    version = selected.get("expected_workout_version")
    if (
        type(version) is not int
        or version < 1
        or request.get("expected_workout_version") != version
    ):
        return False
    read_sets, proposed_sets = selected.get("set_versions"), request.get("set_versions")
    if not isinstance(read_sets, list) or not read_sets or not isinstance(proposed_sets, list):
        return False

    def versions(items: list) -> dict[str, int] | None:
        values: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                return None
            identifier, version = _identifier(item.get("set_id")), item.get("expected_version")
            if (
                identifier is None
                or identifier in values
                or type(version) is not int
                or version < 1
            ):
                return None
            values[identifier] = version
        return values

    read_versions = versions(read_sets)
    return read_versions is not None and read_versions == versions(proposed_sets)


def _review_matches(review: dict, args: dict, selected: dict, spec: dict) -> bool:
    # A later unrelated lookup must not erase an earlier known target or candidate list.
    identity_verified = False
    for value in (args, review):
        for key in spec["ids"]:
            if key in value and value[key] is not None:
                if _identifier(value[key]) != _identifier(selected.get(key)):
                    return False
                identity_verified = True
    candidates = review.get("candidates")
    if isinstance(candidates, list) and candidates:
        ids = {_identity(item, spec) for item in candidates if isinstance(item, dict)} - {None}
        if not ids or _identity(selected, spec) not in ids:
            return False
        identity_verified = True
    for name in ("exercise_name", "day", "workout_date", "meal_type", "set_index"):
        target = args.get(name)
        actual = selected.get("date" if name in {"day", "workout_date"} else name)
        if target is not None and actual is not None:
            if name == "exercise_name" and identity_verified:
                # A verified candidate ID survives canonicalisation of its name.
                continue
            if "".join(str(target).casefold().split()) != "".join(str(actual).casefold().split()):
                return False
    if args.get("food_name"):
        keyword = "".join(str(args["food_name"]).casefold().split())
        items = selected.get("items")
        if not isinstance(items, list) or not any(
            isinstance(item, dict)
            and keyword in "".join(str(item.get("name", "")).casefold().split())
            for item in items
        ):
            return False
    return True


def unresolved_reviews(messages: Sequence[Any]) -> list[dict]:
    """Return chronological needs_review results that lack a later verified resolution.

    Keep the existing ToolMessages intact. A pending card alone is not evidence that
    an ambiguous lookup was resolved. Only the same supported entity's subsequent
    unique read, followed by a version-matched proposal, can retire its old review.
    """
    arguments: dict[str, dict] = {}
    rows: list[tuple[str, dict, dict]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if isinstance(call.get("id"), str) and isinstance(call.get("args"), dict):
                    arguments[call["id"]] = call["args"]
        elif isinstance(message, ToolMessage):
            payload = _payload(message.content)
            if payload is not None:
                rows.append((message.name or "", payload, arguments.get(message.tool_call_id, {})))

    unresolved: list[dict] = []
    for index, (name, review, args) in enumerate(rows):
        if review.get("status") != "needs_review":
            continue
        family = next(
            (
                key
                for key, spec in _FAMILIES.items()
                if name == spec["read"] or name in spec["proposals"]
            ),
            None,
        )
        code = str(review.get("error_code", "")).upper()
        if family is None or any(
            part in code
            for part in (
                "AUTH",
                "PERMISSION",
                "TIMEOUT",
                "DEPENDENCY",
                "RATE_LIMIT",
                "LOOP",
            )
        ):
            unresolved.append(review)
            continue
        spec = _FAMILIES[family]
        resolved = False
        for read_index in range(index + 1, len(rows)):
            read_name, read_result, _ = rows[read_index]
            selected = read_result.get(spec["selected"])
            if (
                read_name != spec["read"]
                or read_result.get("status") != "available"
                or not isinstance(selected, dict)
                or _identity(selected, spec) is None
                or not _review_matches(review, args, selected, spec)
            ):
                continue
            for proposal_name, result, _ in rows[read_index + 1 :]:
                operation = spec["proposals"].get(proposal_name)
                if operation is None or result.get("status") != "confirmation_required":
                    continue
                original_operation = spec["proposals"].get(name)
                if original_operation is not None and original_operation != operation:
                    continue
                try:
                    card = AgentConfirmationCard.model_validate(result.get("confirmation"))
                except ValidationError:
                    continue
                after = card.after
                if (
                    card.status == "pending"
                    and card.operation_type == operation
                    and isinstance(after, dict)
                    and _identity(after, spec) == _identity(selected, spec)
                    and _same_version(selected, after, family)
                ):
                    resolved = True
                    break
            if resolved:
                break
        if not resolved:
            unresolved.append(review)
    return unresolved
