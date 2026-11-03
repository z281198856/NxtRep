"""Small request-scoped execution journal shared by rebuilt Agent tool sets."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        # PATCH services use exclude_unset: omission preserves a value while
        # explicit null may clear it. Preserve presence at every nested level.
        return {
            "fields_set": sorted(value.model_fields_set),
            "values": _canonical({
                name: getattr(value, name) for name in type(value).model_fields
            }),
        }
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Tool numeric arguments must be finite")
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def argument_fingerprint(arguments: dict) -> str:
    canonical = json.dumps(
        _canonical(arguments), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_side_effect(tool_name: str) -> bool:
    return tool_name.startswith("propose_") or tool_name in {
        "save_memory", "update_memory", "delete_memory", "cancel_confirmation",
    }


def _uuid_ref(value: Any) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def side_effect_result_is_valid(tool_name: str, result: Any) -> bool:
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        return False
    status = result["status"]
    if status in {"needs_review", "not_saved", "not_found", "invalid_request", "unavailable",
                  "failed"}:
        return True
    if status == "confirmation_required" or status == "cancelled":
        card = result.get("confirmation")
        return bool(
            isinstance(card, dict)
            and _uuid_ref(card.get("confirmation_id"))
            and isinstance(card.get("operation_type"), str) and card["operation_type"].strip()
            and card.get("status") == ("pending" if status == "confirmation_required" else status)
            and type(card.get("version")) is int and card["version"] >= 1
        )
    if tool_name in {"save_memory", "update_memory", "delete_memory"} and status in {
        "saved", "updated", "deleted",
    }:
        memory = result.get("memory")
        identifier = memory.get("id") if isinstance(memory, dict) else result.get("memory_id")
        version = memory.get("version") if isinstance(memory, dict) else result.get("version")
        return bool(_uuid_ref(identifier) and type(version) is int and version >= 1)
    return False


def _read_progress_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _read_progress_data(item) for key, item in value.items()
            if key not in {"searched_at", "queried_at", "fetched_at", "generated_at",
                           "duration_ms", "tool_call_id"}
        }
    if isinstance(value, list):
        return [_read_progress_data(item) for item in value]
    return value


@dataclass(slots=True)
class AgentToolJournal:
    """Deduplicate successful writes within one run without caching reads or committing.

    Complete results stay in memory for exact replay. Only IDs, fingerprints and
    statuses enter snapshots. A snapshot is evidence of what a tool returned;
    recovery must still check current database ownership and existence, including
    after a transaction rollback. This is not cross-request idempotency.
    """

    max_tool_calls: int = 64
    max_identical_calls_without_progress: int = 3
    _tool_call_count: int = 0
    _progress_epoch: int = 0
    _results: dict[str, dict] = field(default_factory=dict, repr=False)
    _stale_results: dict[str, dict] = field(default_factory=dict, repr=False)
    _unknown: dict[str, dict] = field(default_factory=dict, repr=False)
    _repetitions: dict[tuple[int, str], int] = field(default_factory=dict, repr=False)
    _operations: list[dict] = field(default_factory=list, repr=False)
    _tool_runs: list[dict] = field(default_factory=list, repr=False)
    _confirmation_refs: dict[str, None] = field(default_factory=dict, repr=False)
    _observed_reads: dict[str, str] = field(default_factory=dict, repr=False)

    def replay(self, key: str) -> dict | None:
        result = self._stale_results.get(key) or self._results.get(key)
        return deepcopy(result) if result is not None else None

    def observe_read(self, key: str, result: Any) -> None:
        if not isinstance(result, dict) or result.get("status") not in {
            "available", "not_found", "not_configured", "no_evidence",
        }:
            return
        fingerprint = argument_fingerprint(_read_progress_data(result))
        previous = self._observed_reads.get(key)
        if previous is not None and previous != fingerprint:
            self._repetitions[(self._progress_epoch, key)] = 0
        self._observed_reads[key] = fingerprint

    def note_returned_refs(self, result: Any) -> None:
        card = result.get("confirmation") if isinstance(result, dict) else None
        if isinstance(card, dict) and (identifier := _uuid_ref(card.get("confirmation_id"))):
            self._confirmation_refs[identifier] = None

    def _invalidate_confirmation(self, identifier: str, status: str) -> None:
        for key, result in self._results.items():
            card = result.get("confirmation")
            if key.startswith("propose_") and isinstance(card, dict) and (
                _uuid_ref(card.get("confirmation_id")) == identifier
            ):
                self._stale_results[key] = {
                    "status": "needs_review", "error_code": "TOOL_RESULT_STALE",
                    "confirmation_id": identifier, "current_status": status,
                    "message": "原草稿已取消或被替换，不能复用旧待确认结果。请核对当前草稿。",
                }

    def guard(self, key: str) -> dict | None:
        if key in self._unknown:
            return {
                "status": "needs_review", "error_code": "TOOL_OUTCOME_UNKNOWN",
                "message": "上次操作中断，结果尚未核实。请先核对记录或待确认草稿，不能重复执行。",
            }
        if self._tool_call_count >= self.max_tool_calls:
            return {
                "status": "needs_review", "error_code": "TOOL_CALL_LIMIT",
                "message": "本轮工具调用已达上限。请保留已生成的草稿，核对已有结果后再继续。",
            }
        repetition_key = (self._progress_epoch, key)
        count = self._repetitions.get(repetition_key, 0)
        if count >= self.max_identical_calls_without_progress:
            return {
                "status": "needs_review", "error_code": "TOOL_NO_PROGRESS_LIMIT",
                "message": "相同参数已重复处理且没有新的业务进展，请利用已有结果或补充明确条件。",
            }
        self._repetitions[repetition_key] = count + 1
        self._tool_call_count += 1
        return None

    def succeeded(self, key: str, result: Any, record: dict) -> None:
        if not isinstance(result, dict) or result.get("status") not in {
            "confirmation_required", "saved", "updated", "deleted", "cancelled",
        }:
            return
        self._results[key] = deepcopy(result)
        operation = {
            field: record[field]
            for field in ("tool_name", "status", "argument_fingerprint", "tool_call_id")
        }
        card = result.get("confirmation")
        if isinstance(card, dict) and (identifier := _uuid_ref(card.get("confirmation_id"))):
            operation["confirmation_id"] = identifier
            self._confirmation_refs[identifier] = None
            if card.get("status") == "cancelled":
                self._invalidate_confirmation(identifier, "cancelled")
            after = card.get("after")
            replaced = _uuid_ref(after.get("replaces_confirmation_id")) if (
                isinstance(after, dict)
            ) else None
            if replaced:
                self._invalidate_confirmation(replaced, "rejected")
        memory = result.get("memory")
        resource = result.get("resource_id") or result.get("memory_id")
        if isinstance(memory, dict):
            resource = memory.get("id") or resource
        if identifier := _uuid_ref(resource):
            operation["resource_id"] = identifier
        self._operations.append(operation)
        self._progress_epoch += 1

    def outcome_unknown(self, key: str, record: dict) -> None:
        self._unknown[key] = {
            **{
                field: record[field]
                for field in ("tool_name", "argument_fingerprint", "tool_call_id", "error_code")
            },
            "status": "unknown",
        }

    def record_call(self, record: dict) -> None:
        self._tool_runs.append(deepcopy(record))

    def snapshot(self) -> dict:
        return deepcopy({
            "tool_runs": self._tool_runs[-100:],
            "confirmation_refs": list(self._confirmation_refs),
            "operations": self._operations,
            "unknown_operations": list(self._unknown.values()),
        })
