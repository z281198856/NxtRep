"""Deterministic scoring of consented meal photos with optional weighed truth.

Name recall, portion error and calorie error are independent gates. A successful
HTTP response cannot substitute for an accuracy score or an unprovided truth.
"""

import hashlib
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpectedFood(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aliases: list[str] = Field(min_length=1)
    amount_g: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    kcal: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class PhotoQualitySample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")
    image_path: str = Field(min_length=1)
    expected_foods: list[ExpectedFood] = Field(default_factory=list)
    non_food: bool = False
    max_portion_relative_error: float = Field(default=0.35, gt=0, le=1)
    max_kcal_relative_error: float = Field(default=0.35, gt=0, le=1)

    @model_validator(mode="after")
    def require_truth(self):
        if self.non_food == bool(self.expected_foods):
            raise ValueError("provide expected_foods or mark non_food, exclusively")
        for food in self.expected_foods:
            if any(not alias.strip() for alias in food.aliases):
                raise ValueError("food aliases must not be blank")
        return self


def load_photo_samples(path: Path) -> list[PhotoQualitySample]:
    import json

    samples = [
        PhotoQualitySample.model_validate(value)
        for value in json.loads(path.read_text(encoding="utf-8-sig"))
    ]
    if not samples or len({sample.sample_id for sample in samples}) != len(samples):
        raise ValueError("sample IDs must be unique and the manifest must not be empty")
    for sample in samples:
        image = Path(sample.image_path)
        sample.image_path = str(
            (path.parent / image).resolve() if not image.is_absolute() else image
        )
        if not Path(sample.image_path).is_file():
            raise ValueError(f"image unavailable for sample {sample.sample_id}")
    return samples


def _number(value) -> float | None:
    try:
        parsed = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def score_photo(sample: PhotoQualitySample, payload: dict) -> dict:
    foods = payload["recognition"]["foods"]
    items = payload["calculation"]["items"]
    checks = {}
    if sample.non_food:
        checks["no_invented_food"] = not foods
        checks["no_complete_meal"] = payload["calculation"]["is_complete"] is False
        return {
            "sample_id": sample.sample_id,
            "passed": all(checks.values()),
            "checks": checks,
            "accuracy_truth": "non_food_boundary",
        }

    # Match one detection to one truth item, so duplicates cannot inflate recall.
    used = set()
    matched = []
    for truth in sample.expected_foods:
        found = next(
            (
                i
                for i, food in enumerate(foods)
                if i not in used and any(alias.strip() in food["name"] for alias in truth.aliases)
            ),
            None,
        )
        if found is not None:
            used.add(found)
        matched.append(found)
    recall = len(used) / len(sample.expected_foods)
    precision = len(used) / len(foods) if foods else 0
    checks["food_recall"] = recall == 1
    checks["no_unexpected_food"] = precision == 1
    checks["complete_nutrition"] = payload["calculation"]["is_complete"] is True
    portions, calories, intervals = [], [], []
    for truth, index in zip(sample.expected_foods, matched, strict=True):
        name = truth.aliases[0]
        if index is None:
            if truth.amount_g is not None:
                checks[f"portion:{name}"] = False
                portions.append(None)
            if truth.kcal is not None:
                checks[f"kcal:{name}"] = False
                calories.append(None)
            continue
        detected = foods[index]
        if truth.amount_g is not None:
            grams = _number(detected.get("estimated_amount_g"))
            error = abs(grams - truth.amount_g) / truth.amount_g if grams is not None else None
            portions.append(error)
            checks[f"portion:{name}"] = (
                error is not None and error <= sample.max_portion_relative_error
            )
            low, high = _number(detected.get("amount_min_g")), _number(detected.get("amount_max_g"))
            intervals.append(low is not None and high is not None and low <= truth.amount_g <= high)
        if truth.kcal is not None:
            item = next(
                (item for item in items if item["match"]["detected"]["name"] == detected["name"]),
                {},
            )
            kcal = _number(((item.get("nutrition") or {}).get("estimated") or {}).get("kcal"))
            error = abs(kcal - truth.kcal) / truth.kcal if kcal is not None else None
            calories.append(error)
            checks[f"kcal:{name}"] = error is not None and error <= sample.max_kcal_relative_error

    def mean(values):
        return sum(values) / len(values) if values and all(v is not None for v in values) else None

    return {
        "sample_id": sample.sample_id,
        "passed": all(checks.values()),
        "checks": checks,
        "food_recall": recall,
        "food_precision": precision,
        "portion_mean_relative_error": mean(portions),
        "kcal_mean_relative_error": mean(calories),
        "portion_interval_coverage": sum(intervals) / len(intervals) if intervals else None,
        "weighed_items": sum(food.amount_g is not None for food in sample.expected_foods),
        "calorie_reference_items": sum(food.kcal is not None for food in sample.expected_foods),
        "accuracy_truth": "known_portions"
        if any(food.amount_g for food in sample.expected_foods)
        else "names_only",
    }


def photo_fingerprint(sample: PhotoQualitySample) -> str:
    return hashlib.sha256(Path(sample.image_path).read_bytes()).hexdigest()
