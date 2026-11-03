"""Bounded conversation task data, separate from durable business records."""

from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TaskTransition = Literal["new", "continue", "correct", "resume", "cancel"]
TaskStatus = Literal[
    "collecting", "ready", "awaiting_confirmation", "completed", "cancelled", "failed", "suspended"
]

ID_FIELDS = frozenset(
    {
        "workout_id",
        "session_id",
        "exercise_id",
        "workout_exercise_id",
        "set_id",
        "entry_id",
        "meal_id",
        "food_id",
        "food_version_id",
        "confirmation_id",
        "event_id",
        "plan_id",
        "goal_id",
        "measurement_id",
        "memory_id",
        "target_id",
    }
)
INDEX_FIELDS = frozenset({"item_index", "set_number"})
VERSION_FIELDS = frozenset({"version", "expected_version", "expected_workout_version"})
NUMERIC_FIELDS = {
    "weight_kg": (Decimal("0"), Decimal("9999.999"), False),
    "reps": (Decimal("0"), Decimal("1000"), True),
    "sets": (Decimal("1"), Decimal("20"), True),
    "amount_g": (Decimal("0.001"), Decimal("99999.999"), False),
    "amount_ml": (Decimal("1"), Decimal("5000"), True),
}


def bounded_data(value: Any, *, depth: int = 0) -> Any:
    """Retain only finite, small JSON values; never persist arbitrary runtime objects."""
    if depth > 3:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value.is_finite() else None
    if isinstance(value, int):
        return value if abs(value) <= 10**12 else None
    if isinstance(value, float):
        return value if isfinite(value) and abs(value) <= 10**12 else None
    if isinstance(value, str):
        return value.strip()[:600]
    if isinstance(value, dict):
        return {
            str(key)[:64]: bounded_data(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
            if isinstance(key, str)
        }
    if isinstance(value, (list, tuple)):
        return [bounded_data(item, depth=depth + 1) for item in value[:20]]
    return None


def clean_entities(raw: Any) -> dict[str, str | int]:
    if not isinstance(raw, dict):
        return {}
    result = {}
    for name, value in raw.items():
        if name in ID_FIELDS:
            try:
                result[name] = str(UUID(str(value)))
            except (ValueError, TypeError, AttributeError):
                continue
        elif name in INDEX_FIELDS | VERSION_FIELDS and type(value) is int:
            minimum = 0 if name == "item_index" else 1
            if minimum <= value <= 100_000:
                result[name] = value
    return result


def clean_parameters(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    result = bounded_data(raw)
    for name, (low, high, integer) in NUMERIC_FIELDS.items():
        if name not in result:
            continue
        try:
            value = Decimal(str(result[name]))
            if not value.is_finite() or not low <= value <= high:
                raise ValueError
            if integer and value != value.to_integral_value():
                raise ValueError
            if not integer and value.as_tuple().exponent < -3:
                raise ValueError
        except (ValueError, ArithmeticError):
            result.pop(name)
        else:
            result[name] = int(value) if integer else format(value.normalize(), "f")
    return result


class TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentTaskCandidate(TaskModel):
    kind: str = Field(min_length=1, max_length=40)
    id: UUID
    label: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None
    item_index: int | None = Field(default=None, ge=0, le=100_000)


class AgentTaskUpdate(TaskModel):
    transition: TaskTransition = "continue"
    resume_task_id: UUID | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    reference_entities: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    invalid_fields: list[str] = Field(default_factory=list, max_length=20, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def track_invalid_numbers(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        raw = dict(raw)
        parameters = raw.get("parameters")
        if isinstance(parameters, dict):
            parameters = dict(parameters)
            names, amounts = parameters.get("food_name"), parameters.get("amount_g")
            converted_foods = False
            if (
                isinstance(names, list)
                and isinstance(amounts, list)
                and 1 <= len(names) == len(amounts) <= 20
                and not parameters.get("items")
            ):
                items = []
                for name, amount in zip(names, amounts, strict=True):
                    portion = clean_parameters({"amount_g": amount}).get("amount_g")
                    if not isinstance(name, str) or not name.strip() or portion is None:
                        break
                    items.append({"food_name": name.strip(), "amount_g": portion})
                if len(items) == len(names):
                    parameters["items"] = items
                    parameters.pop("food_name")
                    parameters.pop("amount_g")
                    converted_foods = True
            raw["parameters"] = parameters
            cleaned = clean_parameters(parameters)
            invalid = [
                name for name in NUMERIC_FIELDS if name in parameters and name not in cleaned
            ]
            if "amount_g" in invalid:
                # Preserve the supplied input so the planner can distinguish an
                # unweighed portion from an explicit invalid number. Existing
                # records retain their normal strict correction requirements.
                amount_input = parameters["amount_g"]
                if (
                    isinstance(amount_input, (int, float))
                    and bounded_data(amount_input) is None
                    or isinstance(amount_input, Decimal)
                    and not amount_input.is_finite()
                ):
                    amount_input = str(amount_input)
                parameters["_amount_g_input"] = amount_input
            elif "amount_g" in parameters or converted_foods:
                parameters.pop("_amount_g_input", None)
            elif isinstance(parameters.get("portion"), str) and parameters["portion"].strip():
                parameters["_amount_g_input"] = parameters["portion"]
            previous = raw.get("invalid_fields") or []
            if converted_foods:
                previous = [name for name in previous if name != "amount_g"]
            raw["invalid_fields"] = list(
                dict.fromkeys(
                    [
                        *[name for name in previous if name in NUMERIC_FIELDS],
                        *invalid,
                    ]
                )
            )
        return raw

    _entities = field_validator("entities", mode="before")(clean_entities)
    _references = field_validator("reference_entities", mode="before")(clean_entities)
    _parameters = field_validator("parameters", mode="before")(clean_parameters)


class AgentTask(TaskModel):
    task_id: UUID = Field(default_factory=uuid4)
    task_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    status: TaskStatus = "collecting"
    current_step: str = Field(default="collect_parameters", max_length=80)
    entities: dict[str, Any] = Field(default_factory=dict)
    reference_entities: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    invalid_fields: list[str] = Field(default_factory=list, max_length=20)
    candidates: list[AgentTaskCandidate] = Field(default_factory=list, max_length=20)
    last_tool_call: dict[str, Any] = Field(default_factory=dict)
    last_tool_result: dict[str, Any] = Field(default_factory=dict)

    _entities = field_validator("entities", mode="before")(clean_entities)
    _references = field_validator("reference_entities", mode="before")(clean_entities)
    _parameters = field_validator("parameters", mode="before")(clean_parameters)
    _call = field_validator("last_tool_call", mode="before")(bounded_data)
    _result = field_validator("last_tool_result", mode="before")(bounded_data)


class AgentTaskState(TaskModel):
    schema_version: Literal[1] = 1
    active_task: AgentTask | None = None
    suspended_task: AgentTask | None = None
    suspended_tasks: list[AgentTask] = Field(default_factory=list, max_length=4)


class TaskTurnPreparation(TaskModel):
    state: AgentTaskState
    transition: TaskTransition | None = None
    handled: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, Any] = Field(default_factory=dict)
    selection: AgentTaskCandidate | None = None
    clarification_required: bool = False
    requires_business_action: bool = False
