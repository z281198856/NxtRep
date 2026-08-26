import math
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from nxtrep_backend.db.models import BodyFatEstimate, BodyMeasurement, BodyMeasurementRevision
from nxtrep_backend.repositories.body import SqlAlchemyBodyRepository
from nxtrep_backend.schemas.body import (
    BodyMeasurementCreateRequest,
    BodyMeasurementUpdateRequest,
    NavyBodyFatRequest,
)


class BodyNotFoundError(RuntimeError):
    pass


class BodyConflictError(RuntimeError):
    def __init__(self, message: str, current_version: int | None = None) -> None:
        super().__init__(message)
        self.current_version = current_version


class BodyService:
    def __init__(self, repository: SqlAlchemyBodyRepository) -> None:
        self.repository = repository

    async def create_measurement(
        self, user_id: UUID, body: BodyMeasurementCreateRequest
    ) -> BodyMeasurement:
        return await self.repository.add_measurement(
            BodyMeasurement(user_id=user_id, **body.model_dump())
        )

    async def update_measurement(
        self, user_id: UUID, item_id: UUID, body: BodyMeasurementUpdateRequest
    ) -> BodyMeasurement:
        item = await self.repository.get_measurement(user_id, item_id, lock=True)
        if item is None:
            raise BodyNotFoundError("Body measurement not found")
        if item.version != body.expected_version:
            raise BodyConflictError("Body measurement was modified", item.version)
        fields = body.model_fields_set - {"reason", "expected_version"}
        old = self._snapshot(item)
        for name in fields:
            setattr(item, name, getattr(body, name))
        if all(
            getattr(item, name) is None for name in ("weight_kg", "waist_cm", "neck_cm", "hip_cm")
        ):
            raise BodyConflictError("At least one measurement is required", item.version)
        item.version += 1
        await self.repository.add_revision(
            BodyMeasurementRevision(
                measurement_id=item.id,
                old_values=old,
                new_values=self._snapshot(item),
                reason=body.reason,
            )
        )
        return item

    async def navy_body_fat(self, user_id: UUID, body: NavyBodyFatRequest) -> dict:
        inches = Decimal("0.3937007874")
        height = float(body.height_cm * inches)
        waist = float(body.waist_cm * inches)
        neck = float(body.neck_cm * inches)
        if body.sex == "male":
            value = 86.010 * math.log10(waist - neck) - 70.041 * math.log10(height) + 36.76
        else:
            hip = float((body.hip_cm or Decimal("0")) * inches)
            value = 163.205 * math.log10(waist + hip - neck) - 97.684 * math.log10(height) - 78.387
        rounded = Decimal(str(max(2.0, min(value, 70.0)))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        result = {
            "method": "navy",
            "value_percent": rounded,
            "range_min_percent": max(Decimal("0"), rounded - Decimal("3.00")),
            "range_max_percent": rounded + Decimal("3.00"),
            "confidence": "medium",
        }
        if body.save:
            await self.repository.add_body_fat(
                BodyFatEstimate(
                    user_id=user_id,
                    calculated_at=datetime.now(UTC),
                    method="navy",
                    inputs=body.model_dump(mode="json", exclude={"save"}),
                    value_percent=result["value_percent"],
                    range_min_percent=result["range_min_percent"],
                    range_max_percent=result["range_max_percent"],
                    confidence="medium",
                )
            )
        return result

    async def overview(self, user_id: UUID, start_date: date, end_date: date) -> dict:
        workouts, entries, measurements, records = await self.repository.progress_rows(
            user_id, start_date, end_date
        )
        completed = [item for item in workouts if item.status == "completed"]
        total_minutes = sum(
            int((item.ended_at - item.started_at).total_seconds() / 60)
            for item in completed
            if item.ended_at
        )
        consumed = [Decimal(str(item.totals["kcal"])) for item in entries]
        weighted = [item.weight_kg for item in measurements if item.weight_kg is not None]
        completion = Decimal(len(completed)) / Decimal(len(workouts)) if workouts else Decimal("0")
        completeness = min(
            Decimal(len(entries)) / Decimal(max((end_date - start_date).days + 1, 1)), Decimal("1")
        )
        return {
            "training": {
                "workout_count": len(workouts),
                "completion_rate": str(completion.quantize(Decimal("0.01"))),
                "total_duration_minutes": total_minutes,
                "pr_count": len(records),
            },
            "nutrition": {
                "average_kcal": str(
                    (sum(consumed, Decimal("0")) / Decimal(len(consumed))).quantize(Decimal("0.01"))
                    if consumed
                    else Decimal("0.00")
                ),
                "record_completeness": str(completeness.quantize(Decimal("0.01"))),
            },
            "body": {
                "weight_start_kg": str(weighted[0]) if weighted else None,
                "weight_end_kg": str(weighted[-1]) if weighted else None,
                "smoothed_change_kg": str((weighted[-1] - weighted[0]).quantize(Decimal("0.01")))
                if len(weighted) >= 2
                else None,
            },
        }

    async def body_trend(
        self, user_id: UUID, metric: str, start_date: date, end_date: date, window: str
    ) -> list[dict]:
        if metric == "body_fat":
            rows = await self.repository.body_fat_in_range(user_id, start_date, end_date)
            values = [(item.calculated_at.date(), item.value_percent) for item in rows]
        else:
            rows = await self.repository.measurements_in_range(user_id, start_date, end_date)
            attr = "weight_kg" if metric == "weight" else "waist_cm"
            values = [
                (item.measured_at.date(), getattr(item, attr))
                for item in rows
                if getattr(item, attr) is not None
            ]
        size = {"raw": 1, "7d": 7, "14d": 14}[window]
        points = []
        for index, (day, raw) in enumerate(values):
            recent = [value for _, value in values[max(0, index - size + 1) : index + 1]]
            smooth = sum(recent, Decimal("0")) / Decimal(len(recent))
            points.append({"date": day, "raw_value": raw, "smoothed_value": smooth})
        return points

    @staticmethod
    def _snapshot(item: BodyMeasurement) -> dict:
        return {
            name: (
                str(value)
                if isinstance(value, Decimal)
                else value.isoformat()
                if isinstance(value, datetime)
                else value
            )
            for name, value in {
                "measured_at": item.measured_at,
                "weight_kg": item.weight_kg,
                "waist_cm": item.waist_cm,
                "neck_cm": item.neck_cm,
                "hip_cm": item.hip_cm,
                "source": item.source,
                "conditions": item.conditions,
                "notes": item.notes,
                "version": item.version,
            }.items()
        }
