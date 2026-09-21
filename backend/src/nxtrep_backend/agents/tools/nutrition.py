from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionTargetDraftRequest,
)


def build_nutrition_read_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def search_food_candidates(
        keyword: str,
        region: str | None = None,
        state: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search visible food catalog entries for nutrition logging."""
        safe_limit = min(max(limit, 1), 20)
        rows, total = await context.nutrition_service.search_foods(
            user_id=context.user_id,
            keyword=keyword,
            region=region,
            state=state,
            page=1,
            page_size=safe_limit,
        )
        return {
            "status": "available",
            "total": total,
            "returned_count": len(rows),
            "has_more": safe_limit < total,
            "foods": [
                {
                    "id": str(food.id),
                    "food_version_id": str(version.id),
                    "name": food.name,
                    "brand": food.brand,
                    "state": food.state,
                    "basis_amount_g": str(version.basis_amount_g),
                    "kcal": str(version.kcal),
                    "protein_g": str(version.protein_g),
                    "carbs_g": str(version.carbs_g),
                    "fat_g": str(version.fat_g),
                    "source": version.source,
                    "confidence": version.confidence,
                }
                for food, version in rows
            ],
        }

    @tool
    async def read_nutrition_entries(
        day: date,
        meal_type: Literal[
            "breakfast",
            "lunch",
            "dinner",
            "snack",
            "other",
        ]
        | None = None,
    ) -> dict:
        """Read nutrition entries for one day, optionally filtered by meal."""
        entries = await context.nutrition_service.list_entries(
            user_id=context.user_id,
            day=day,
            meal_type=meal_type,
        )
        return {
            "status": "available",
            "date": day.isoformat(),
            "entries": [
                {
                    "id": str(item.id),
                    "meal_type": item.meal_type,
                    "eaten_at": item.eaten_at.isoformat(),
                    "items": json_safe(item.items),
                    "totals": json_safe(item.totals),
                    "is_flexible_meal": item.is_flexible_meal,
                    "notes": item.notes,
                }
                for item in entries
            ],
        }

    @tool
    async def read_daily_nutrition_summary(day: date) -> dict:
        """Read consumed, target, remaining nutrients, and completeness for a day."""
        summary = await context.nutrition_service.daily_summary(
            context.user_id,
            day,
        )
        return {"status": "available", **json_safe(summary)}

    return [
        search_food_candidates,
        read_nutrition_entries,
        read_daily_nutrition_summary,
    ]


def build_nutrition_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def propose_nutrition_entry(
        meal_type: Literal[
            "breakfast",
            "lunch",
            "dinner",
            "snack",
            "other",
        ],
        eaten_at: datetime,
        items: list[NutritionItemInput],
        is_flexible_meal: bool = False,
        notes: str | None = None,
    ) -> dict:
        """Validate a meal and create a confirmation before saving it."""
        confirmation = await context.nutrition_service.propose_entry(
            user_id=context.user_id,
            body=NutritionEntryCreateRequest(
                meal_type=meal_type,
                eaten_at=eaten_at,
                items=items,
                is_flexible_meal=is_flexible_meal,
                notes=notes,
            ),
        )
        return {
            "status": "confirmation_required",
            "confirmation": confirmation_payload(confirmation),
        }

    @tool
    async def propose_nutrition_target(
        effective_from: date,
        kcal_min: Decimal,
        kcal_max: Decimal,
        protein_min_g: Decimal,
        protein_max_g: Decimal,
        carbs_min_g: Decimal,
        carbs_max_g: Decimal,
        fat_min_g: Decimal,
        fat_max_g: Decimal,
    ) -> dict:
        """Propose nutrition targets and create a confirmation before activation."""
        draft = await context.nutrition_service.create_target_draft(
            context.user_id,
            NutritionTargetDraftRequest(
                effective_from=effective_from,
                kcal_min=kcal_min,
                kcal_max=kcal_max,
                protein_min_g=protein_min_g,
                protein_max_g=protein_max_g,
                carbs_min_g=carbs_min_g,
                carbs_max_g=carbs_max_g,
                fat_min_g=fat_min_g,
                fat_max_g=fat_max_g,
            ),
        )
        confirmation = await context.nutrition_service.submit_target(
            context.user_id,
            draft.id,
            draft.version,
        )
        return {
            "status": "confirmation_required",
            "draft": {
                "id": str(draft.id),
                "version": draft.version,
                "status": draft.status,
                "effective_from": draft.effective_from.isoformat(),
            },
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_nutrition_entry, propose_nutrition_target]
