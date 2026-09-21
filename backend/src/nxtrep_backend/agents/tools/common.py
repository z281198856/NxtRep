from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def confirmation_payload(item: Any) -> dict[str, Any]:
    return {
        "confirmation_id": str(item.id),
        "operation_type": item.operation_type,
        "status": item.status,
        "before": json_safe(item.before),
        "after": json_safe(item.after),
        "impact": item.impact,
        "expires_at": json_safe(item.expires_at),
        "version": item.version,
    }
