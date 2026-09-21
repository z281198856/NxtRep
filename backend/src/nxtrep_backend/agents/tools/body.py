from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.body import (
    BodyMeasurementCreateRequest,
    NavyBodyFatRequest,
)


def build_body_read_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_body_progress(
        start_date: date,
        end_date: date,
        metric: Literal["weight", "waist", "body_fat"] = "weight",
        window: Literal["raw", "7d", "14d"] = "7d",
    ) -> dict:
        """Read progress overview and a body metric trend for up to one year."""
        if start_date > end_date:
            return {
                "status": "invalid_request",
                "message": "start_date must not exceed end_date.",
            }
        if (end_date - start_date).days > 365:
            return {
                "status": "invalid_request",
                "message": "The progress range must not exceed 366 days.",
            }
        overview = await context.body_service.overview(
            context.user_id,
            start_date,
            end_date,
        )
        points = await context.body_service.body_trend(
            context.user_id,
            metric,
            start_date,
            end_date,
            window,
        )
        return {
            "status": "available",
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "overview": json_safe(overview),
            "trend": {
                "metric": metric,
                "window": window,
                "points": json_safe(points),
            },
        }

    @tool
    async def read_personal_records(
        exercise_id: UUID | None = None,
        record_type: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Read recent personal records, optionally for one exercise or record type."""
        safe_limit = min(max(limit, 1), 50)
        records, total = await context.body_service.list_personal_records(
            user_id=context.user_id,
            exercise_id=exercise_id,
            record_type=record_type,
            page=1,
            page_size=safe_limit,
        )
        return {
            "status": "available",
            "total": total,
            "has_more": safe_limit < total,
            "records": [
                {
                    "exercise_id": (str(item.exercise_id) if item.exercise_id else None),
                    "exercise_name": item.exercise_name_snapshot,
                    "record_type": item.record_type,
                    "value": str(item.value),
                    "occurred_at": item.occurred_at.isoformat(),
                    "workout_id": str(item.workout_id),
                }
                for item in records
            ],
        }

    @tool
    async def calculate_navy_body_fat_range(
        sex: Literal["male", "female"],
        height_cm: Decimal,
        waist_cm: Decimal,
        neck_cm: Decimal,
        hip_cm: Decimal | None = None,
    ) -> dict:
        """Calculate a non-medical Navy body-fat estimate without saving it."""
        result = await context.body_service.navy_body_fat(
            context.user_id,
            NavyBodyFatRequest(
                sex=sex,
                height_cm=height_cm,
                waist_cm=waist_cm,
                neck_cm=neck_cm,
                hip_cm=hip_cm,
                save=False,
            ),
        )
        return {
            "status": "available",
            **json_safe(result),
            "disclaimer": "结果仅用于观察趋势，不是医学测量",
        }

    return [
        read_body_progress,
        read_personal_records,
        calculate_navy_body_fat_range,
    ]


def build_body_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def propose_body_measurement(
        measured_at: datetime,
        source: str,
        weight_kg: Decimal | None = None,
        waist_cm: Decimal | None = None,
        neck_cm: Decimal | None = None,
        hip_cm: Decimal | None = None,
        body_fat_percent: Decimal | None = None,
        body_fat_method: str | None = None,
        conditions: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Propose a body measurement and require confirmation before saving."""
        confirmation = await context.body_service.propose_measurement(
            user_id=context.user_id,
            body=BodyMeasurementCreateRequest(
                measured_at=measured_at,
                weight_kg=weight_kg,
                waist_cm=waist_cm,
                neck_cm=neck_cm,
                hip_cm=hip_cm,
                body_fat_percent=body_fat_percent,
                body_fat_method=body_fat_method,
                source=source,
                conditions=conditions,
                notes=notes,
            ),
        )
        return {
            "status": "confirmation_required",
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_body_measurement]
