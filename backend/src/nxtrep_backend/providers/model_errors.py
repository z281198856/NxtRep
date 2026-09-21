from __future__ import annotations

from typing import Any


class VisionModelBusyError(RuntimeError):
    """Raised when every eligible vision model is temporarily capacity limited."""


def is_model_capacity_error(error: BaseException) -> bool:
    """Recognize OpenAI-compatible 429 responses without binding to one SDK class."""
    current: BaseException | None = error
    visited: set[int] = set()

    for _ in range(8):
        if current is None or id(current) in visited:
            break
        visited.add(id(current))

        if _status_code(current) == 429 or _provider_code(current) == "1305":
            return True

        cause = current.__cause__
        current = cause if isinstance(cause, BaseException) else current.__context__

    return False


def _status_code(error: BaseException) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _provider_code(error: BaseException) -> str | None:
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None

    payload: Any = body.get("error", body)
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    return str(code) if code is not None else None
