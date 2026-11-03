from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import Field

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.nutrition import (
    CustomFoodDraftRequest,
    CustomFoodPatchRequest,
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionPortionChange,
    NutritionTargetDraftRequest,
)
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionNotFoundError


class AgentNutritionItemInput(NutritionItemInput):
    nutrient_basis: Literal["per_basis", "total_consumed"] = Field(
        default="per_basis",
        description=(
            "total_consumed: kcal/protein/carbs/fat are totals for amount_g; "
            "per_basis means nutrients for basis_amount_g, multiplied by amount_g/basis_amount_g. "
            "Prefer total_consumed for custom portions to avoid double-counting."
        ),
    )


class AgentMealReplacementInput(NutritionItemInput):
    item_index: int = Field(ge=0)


def normalize_agent_items(items: list[AgentNutritionItemInput]) -> list[NutritionItemInput]:
    return [
        NutritionItemInput.model_validate(
            {
                **item.model_dump(exclude={"nutrient_basis"}),
                **(
                    {
                        "source": "model_estimated",
                        "confidence": "low",
                        **(
                            {"basis_amount_g": item.amount_g}
                            if item.nutrient_basis == "total_consumed"
                            else {}
                        ),
                    }
                    if item.food_version_id is None
                    else {}
                ),
            }
        )
        for item in items
    ]


def build_nutrition_read_tools(context: AgentToolContext) -> list[BaseTool]:
    search_attempts = 0

    @tool
    async def search_food_candidates(
        keyword: str,
        region: str | None = None,
        state: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search the food catalog up to six times; estimate missing foods after the limit."""
        nonlocal search_attempts
        if search_attempts >= 6:
            return {
                "status": "unavailable",
                "error_code": "FOOD_SEARCH_LIMIT",
                "foods": [],
                "message": "食品库检索次数已达上限，请保留已找到的条目，缺失食物用"
                "常见成品份量估算并标为 model_estimated/low；停止换关键词检索，继续生成草稿。",
            }
        search_attempts += 1
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
                    "is_custom": getattr(food, "owner_user_id", None) == context.user_id,
                    "version": getattr(version, "version", None),
                    "barcode": getattr(food, "barcode", None),
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
                    "version": item.version,
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

    @tool
    async def calculate_meal_option(day: date, items: list[AgentNutritionItemInput]) -> dict:
        """Preview an unsaved meal/substitution against saved targets and preferences.

        Use catalog food_version_id when available; custom totals use total_consumed.
        Read saved goals and constraints before choosing foods. Negative remaining
        values indicate excess. This tool never logs a meal or creates a confirmation.
        """
        result = await context.nutrition_service.preview_meal_option(
            context.user_id, day, normalize_agent_items(items)
        )
        preferences = {"allergies": [], "dietary_preferences": [], "recorded": False}
        try:
            saved = await context.goals_service.get_goals_and_constraints(user_id=context.user_id)
        except GoalsNotFoundError:
            pass
        else:
            preferences = {
                "allergies": saved.constraints.allergies,
                "dietary_preferences": saved.constraints.dietary_preferences,
                "recorded": True,
            }
        conflicts = [
            allergy
            for allergy in preferences["allergies"]
            if any(allergy.casefold() in item["name"].casefold() for item in result["items"])
        ]
        return {
            "status": "available",
            **json_safe(result),
            "preferences": preferences,
            "allergen_name_conflicts": conflicts,
            "suitable": False if conflicts else None,
            "ingredient_warning": (
                "食物名称匹配不能验证完整配料或交叉接触；有过敏记录时须核对配料。"
            ),
        }

    return [
        search_food_candidates,
        read_nutrition_entries,
        read_daily_nutrition_summary,
        calculate_meal_option,
    ]


def build_food_catalog_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    proposals: dict[str, dict] = {}
    read_versions: dict[UUID, int] = {}
    changes: dict[tuple[str, UUID, int, str, str], dict] = {}

    @tool
    async def propose_custom_food(food: CustomFoodDraftRequest) -> dict:
        """Propose one custom food for the personal catalog; approval is required.

        Nutrients are for basis_amount_g grams, never a fictitious 1g serving.
        Mark estimated weight/nutrients model_estimated/low and explain assumptions in notes.
        Does not create a meal or memory. Call separately for distinct foods.
        """
        key = food.model_dump_json(exclude_unset=True)
        if key in proposals:
            return proposals[key]
        confirmation = await context.nutrition_service.propose_custom_food(
            user_id=context.user_id,
            body=food,
        )
        result = {
            "status": "confirmation_required",
            "draft": confirmation.after["food"],
            "confirmation": confirmation_payload(confirmation),
        }
        proposals[key] = result
        return result

    @tool
    async def read_custom_food(
        food_id: UUID | None = None,
        keyword: str | None = None,
        brand: str | None = None,
    ) -> dict:
        """Read an owned custom food's real current version before editing or deleting it.

        Search first; ask which food if multiple candidates match. Public foods are read-only.
        """
        if food_id is None:
            if not keyword or not keyword.strip():
                return {"status": "needs_review", "message": "请提供要修改或删除的自定义食品名称。"}
            rows, total = await context.nutrition_service.search_foods(
                user_id=context.user_id,
                keyword=keyword.strip(),
                region=None,
                state=None,
                page=1,
                page_size=20,
                custom_only=True,
            )
            candidates = [
                (food, version)
                for food, version in rows
                if brand is None or (food.brand or "").casefold() == brand.strip().casefold()
            ]
            exact = [
                (food, version)
                for food, version in candidates
                if food.name.strip().casefold() == keyword.strip().casefold()
            ]
            if exact:
                candidates = exact
            if len(candidates) != 1 or total > 20:
                return {
                    "status": "needs_review",
                    "error_code": "CUSTOM_FOOD_SELECTION_REQUIRED",
                    "message": "未找到唯一匹配的自定义食品，请核对名称或选择要操作的品牌/条目。",
                    "candidates": [
                        {
                            "food_id": str(food.id),
                            "name": food.name,
                            "brand": food.brand,
                            "basis_amount_g": str(version.basis_amount_g),
                        }
                        for food, version in candidates
                    ],
                }
            food_id = candidates[0][0].id
        try:
            food, version = await context.nutrition_service.get_custom_food(
                context.user_id, food_id
            )
        except NutritionNotFoundError as exc:
            return {
                "status": "needs_review",
                "error_code": "CUSTOM_FOOD_NOT_FOUND",
                "message": str(exc),
            }
        read_versions[food.id] = version.version
        return {
            "status": "available",
            "food_id": str(food.id),
            "version": version.version,
            "food": context.nutrition_service.custom_food_snapshot(food, version),
        }

    async def propose_change(
        action: str,
        food_id: UUID,
        expected_version: int,
        patch: CustomFoodPatchRequest | None,
        reason: str,
    ) -> dict:
        if read_versions.get(food_id) != expected_version:
            return {
                "status": "needs_review",
                "error_code": "CUSTOM_FOOD_NOT_READ",
                "message": "请先读取这项自定义食品的最新内容和版本，再生成修改或删除草稿。",
            }
        key = (
            action,
            food_id,
            expected_version,
            patch.model_dump_json(exclude_unset=True) if patch is not None else "",
            reason,
        )
        if key in changes:
            # Reuse only the same command; a corrected nutrient/portion patch
            # must not receive a previous draft with different values.
            return changes[key]
        try:
            confirmation = await context.nutrition_service.propose_custom_food_change(
                user_id=context.user_id,
                food_id=food_id,
                expected_version=expected_version,
                patch=patch,
                reason=reason,
            )
        except (NutritionNotFoundError, NutritionConflictError) as exc:
            return {
                "status": "needs_review",
                "error_code": "CUSTOM_FOOD_CHANGED",
                "message": str(exc),
            }
        result = {
            "status": "confirmation_required",
            "draft": confirmation.after["food"],
            "confirmation": confirmation_payload(confirmation),
        }
        changes[key] = result
        return result

    @tool
    async def propose_custom_food_update(
        food_id: UUID,
        expected_version: int,
        changes: CustomFoodPatchRequest,
    ) -> dict:
        """Propose an owned custom food edit; read_custom_food and user approval are required.

        Pass only requested fields; missing fields preserve existing values.
        Nutrients are for the reference grams. Changing basis_amount_g scales unspecified
        nutrients automatically. Explain edits in notes; never claim the edit is already saved.
        """
        return await propose_change("update", food_id, expected_version, changes, changes.notes)

    @tool
    async def propose_custom_food_delete(
        food_id: UUID,
        expected_version: int,
        reason: str = "用户要求删除自定义食品",
    ) -> dict:
        """Propose removing one owned food from the catalog after read_custom_food.

        Does not delete historical meals or snapshots. Ask which food when ambiguous.
        The user must approve this card before deletion; do not call this to cancel a draft.
        """
        return await propose_change("delete", food_id, expected_version, None, reason)

    return [
        propose_custom_food,
        read_custom_food,
        propose_custom_food_update,
        propose_custom_food_delete,
    ]


def build_nutrition_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def propose_nutrition_entry_from_reference(
        source_entry_id: UUID,
        expected_source_version: Annotated[int, Field(ge=1)],
        meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"],
        eaten_at: datetime,
        replacements: list[AgentMealReplacementInput],
        notes: str,
        additions: list[AgentNutritionItemInput] | None = None,
        remove_item_indices: list[Annotated[int, Field(ge=0)]] | None = None,
    ) -> dict:
        """Draft a NEW meal based on an owned saved meal, never modify the source.

        Read the source with read_nutrition_entries first for its ID, version and item indices.
        replacements: item_index is the source's zero-based item to replace.
        additions appends NEW foods; NEVER replace an existing food to add one.
        remove_item_indices removes only explicitly requested source items.
        An empty replacements list copies all items. Unmentioned foods retain saved amounts
        and nutrition. New estimated foods need complete per-basis nutrition and assumptions.
        The NEW date/meal/time must follow this turn. Approval is required.
        """
        try:
            source = await context.nutrition_service.get_saved_entry(
                context.user_id, source_entry_id,
            )
            if source.version != expected_source_version:
                return {"status": "needs_review", "error_code": "REFERENCE_VERSION_CONFLICT",
                        "message": "参考餐食已变化，请重新读取后生成新餐草稿。"}
            indices = [item.item_index for item in replacements]
            removals = remove_item_indices or []
            if (len(indices) != len(set(indices)) or len(removals) != len(set(removals))
                or set(indices) & set(removals)
                or any(i >= len(source.items) for i in [*indices, *removals])):
                return {"status": "needs_review", "error_code": "REFERENCE_ITEM_CONFLICT",
                        "message": "替换食物的位置不对应参考餐食，请重新读取核对。"}
            changes = {item.item_index: item for item in replacements}
            fields = set(NutritionItemInput.model_fields)
            items = []
            for index, snapshot in enumerate(source.items):
                if index in removals:
                    continue
                if index in changes:
                    data = changes[index].model_dump(exclude={"item_index"})
                    if data.get("food_version_id") is None:
                        data.update(source="model_estimated", confidence="low")
                else:
                    data = {k: v for k, v in snapshot.items() if k in fields}
                items.append(NutritionItemInput.model_validate(data))
            items.extend(normalize_agent_items(additions or []))
            if not items:
                return {"status": "needs_review", "error_code": "EMPTY_REFERENCE_MEAL",
                        "message": "新餐不能没有食物，请核对要保留或新增的食物。"}
            body = NutritionEntryCreateRequest(
                meal_type=meal_type, eaten_at=eaten_at, items=items, notes=notes,
            )
            card = await context.nutrition_service.propose_entry(user_id=context.user_id, body=body)
            operations = {"source_entry_id": str(source.id),
                          "source_item_count": len(source.items),
                          "replaced_item_indices": indices, "removed_item_indices": removals,
                          "added_items": [item.name for item in items[-len(additions or []):]]
                          if additions else [], "result_item_count": len(items)}
            card.after = {**card.after, "reference_operations": operations}
        except (NutritionNotFoundError, NutritionConflictError) as exc:
            return {"status": "needs_review", "message": str(exc)}
        return {"status": "confirmation_required", "draft": body.model_dump(mode="json"),
                "reference_entry_id": str(source.id), "applied_operations": operations,
                "confirmation": confirmation_payload(card)}

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
        items: list[AgentNutritionItemInput],
        is_flexible_meal: bool = False,
        notes: str | None = None,
    ) -> dict:
        """Create a meal confirmation. Custom estimates should use nutrient_basis=total_consumed.

        For total_consumed, send nutrient totals for the eaten amount_g, not per 100g.
        Catalog items use stored food-version nutrients. Nothing is saved until approval.
        """
        items = normalize_agent_items(items)
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
            "draft": {
                **confirmation.after.get("entry", {}),
                **confirmation.after.get("preview", {}),
            },
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
                "values": json_safe(draft.values),
            },
            "confirmation": confirmation_payload(confirmation),
        }

    @tool
    async def propose_nutrition_entry_revision(
        confirmation_id: UUID,
        expected_version: int,
        changes: list[NutritionPortionChange],
        notes: str | None = None,
        additions: list[AgentNutritionItemInput] | None = None,
        remove_item_indices: list[Annotated[int, Field(ge=0)]] | None = None,
    ) -> dict:
        """Revise a pending meal's portions or model estimates; invalidate its old card.

        First read/list actual pending confirmations. item_index is zero based.
        Only change user-requested items. No actual meal is saved until new approval.
        For a different food use changes[].replacement with complete food/portion/nutrition;
        name alone is not a food replacement. additions appends foods, changes=[] is allowed.
        remove_item_indices removes source items; retain all other foods.
        For cooking/estimate feedback, keep amount_g omitted unless explicitly changed.
        nutrition_estimate supplies ALL FOUR TOTAL nutrients for the eaten portion,
        with assumptions explaining ingredients/oil and uncertainty. Catalog nutrients
        cannot be replaced. Do not ask the user to calculate grams of fat or oil.
        """
        try:
            confirmation = await context.nutrition_service.revise_pending_entry(
                context.user_id,
                confirmation_id,
                NutritionPendingEntryRevisionRequest(
                    expected_version=expected_version,
                    changes=changes,
                    additions=normalize_agent_items(additions or []),
                    remove_item_indices=remove_item_indices or [],
                    notes=notes,
                ),
            )
        except (NutritionNotFoundError, NutritionConflictError) as exc:
            return {
                "status": "needs_review",
                "error_code": "MEAL_REVISION_REVIEW_REQUIRED",
                "message": str(exc),
            }
        return {
            "status": "confirmation_required",
            "draft": {**confirmation.after["entry"], **confirmation.after["preview"]},
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_nutrition_entry, propose_nutrition_target, propose_nutrition_entry_revision,
            propose_nutrition_entry_from_reference]
