from datetime import UTC, date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import Field

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.schemas.nutrition import (
    NutritionDateChangeRequest,
    NutritionEntryDeleteRequest,
    NutritionSavedEntryRevisionRequest,
)
from nxtrep_backend.services.confirmation import DatabaseConfirmationNotFoundError
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionNotFoundError


def build_saved_meal_change_tools(context: AgentToolContext) -> list[BaseTool]:
    read_versions: dict[UUID, int] = {}
    read_item_targets: dict[UUID, set[int] | None] = {}
    proposals: dict[str, dict] = {}

    @tool
    async def read_saved_meal_for_change(
        day: date | None = None,
        meal_type: Literal["breakfast", "lunch", "dinner", "snack", "other"] | None = None,
        food_name: str | None = None,
        eaten_time: str | None = None,
        entry_id: UUID | None = None,
        all_meals: bool = False,
    ) -> dict:
        """Read owned saved meals by date/meal/food/time (HH:MM) or actual ID; ask on ambiguity.

        Returns zero-based food item_index and immutable original nutrient snapshots.
        A matching meal is not a pending draft or a food catalog item.
        """
        if day is None and entry_id is None:
            return {"status": "needs_review", "message": "请先确定是哪一天或哪条已保存饮食记录。"}
        if eaten_time is not None:
            try:
                clock = time.fromisoformat(eaten_time)
            except ValueError:
                return {"status": "needs_review", "message": "请核对这餐的记录时间。"}
        else:
            clock = None
        if entry_id:
            try:
                entries = [
                    await context.nutrition_service.get_saved_entry(context.user_id, entry_id)
                ]
            except NutritionNotFoundError:
                entries = []
        else:
            entries = await context.nutrition_service.list_entries(
                user_id=context.user_id,
                day=day,
                meal_type=meal_type,
            )
        candidates = []
        scope = getattr(context, "task_scope", {})
        pending_id = scope.get("confirmation_id") if isinstance(scope, dict) else None
        pending = (
            await context.confirmation_service.get(
                user_id=context.user_id, confirmation_id=UUID(str(pending_id))
            )
            if pending_id
            else None
        )
        keyword = "".join((food_name or "").casefold().split())
        for entry in entries:
            local = entry.eaten_at.astimezone(CHINA_TIMEZONE)
            if day and local.date() != day or meal_type and entry.meal_type != meal_type:
                continue
            if clock and (local.hour, local.minute) != (clock.hour, clock.minute):
                continue
            foods = [{"item_index": i, **json_safe(item)} for i, item in enumerate(entry.items)]
            totals = json_safe(entry.totals)
            pending_context = {}
            if (
                pending is not None
                and pending.status == "pending"
                and pending.operation_type == "nutrition_entry_update"
                and pending.expires_at > datetime.now(UTC)
                and pending.after.get("entry_id") == str(entry.id)
            ):
                correction = NutritionSavedEntryRevisionRequest.model_validate(
                    {
                        "expected_version": pending.after["expected_version"],
                        "changes": pending.after.get("changes", []),
                        "remove_item_indices": pending.after.get("remove_item_indices", []),
                        "reason": pending.reason or "待确认餐食更正",
                    }
                )
                if correction.expected_version != entry.version:
                    return {
                        "status": "needs_review",
                        "message": "这餐在更正草稿创建后已变化，请重新核对。",
                    }
                effective, totals = await context.nutrition_service.preview_saved_revision(
                    context.user_id, entry, correction
                )
                indices = [
                    i for i in range(len(entry.items)) if i not in correction.remove_item_indices
                ]
                foods = [
                    {"item_index": index, **json_safe(item)}
                    for index, item in zip(indices, effective, strict=True)
                ]
                pending_context = {
                    "pending_confirmation_id": str(pending.id),
                    "saved_totals": json_safe(entry.totals),
                    "nutrition_state": "pending_revision_preview",
                }
            matches = [
                item
                for item in foods
                if keyword in "".join(str(item.get("name", "")).casefold().split())
            ]
            exact = [
                item
                for item in matches
                if keyword and keyword == "".join(str(item.get("name", "")).casefold().split())
            ]
            matches = exact or matches
            if keyword and not matches:
                continue
            candidates.append(
                {
                    "entry_id": str(entry.id),
                    "version": entry.version,
                    "date": local.date().isoformat(),
                    "meal_type": entry.meal_type,
                    "eaten_at": local.isoformat(),
                    "items": foods,
                    "matching_item_indices": [item["item_index"] for item in matches],
                    "totals": totals,
                    "notes": entry.notes,
                    **pending_context,
                }
            )
        if all_meals and candidates:
            if len(candidates) > 50:
                return {"status": "needs_review", "message": "匹配餐食超过50条，请缩小到具体餐次。"}
            for selected in candidates:
                read_versions[UUID(selected["entry_id"])] = selected["version"]
                read_item_targets[UUID(selected["entry_id"])] = None
            return {"status": "available", "selected_entries": candidates}
        if len(candidates) != 1 or keyword and len(candidates[0]["matching_item_indices"]) != 1:
            return {
                "status": "needs_review",
                "candidates": candidates[:20],
                "has_more": len(candidates) > 20,
                "message": "有多个匹配的餐食或同名食物，请选择记录时间和具体食物。"
                if candidates
                else "未找到对应已保存饮食，请核对日期、餐次或食物名称。",
            }
        selected = candidates[0]
        read_versions[UUID(selected["entry_id"])] = selected["version"]
        read_item_targets[UUID(selected["entry_id"])] = (
            set(selected["matching_item_indices"]) if keyword else None
        )
        return {"status": "available", "selected_entry": selected}

    async def propose(entry_id, body):
        if read_versions.get(entry_id) != body.expected_version:
            return {"status": "needs_review", "message": "请先读取并核对这条已保存饮食的最新内容。"}
        targets = read_item_targets.get(entry_id)
        if targets is not None and isinstance(body, NutritionSavedEntryRevisionRequest):
            touched = {c.item_index for c in getattr(body, "changes", [])}
            touched.update(getattr(body, "remove_item_indices", []))
            if touched - targets:
                return {"status": "needs_review", "error_code": "READ_ITEM_CONFLICT",
                        "message": "本次修改与刚读取选中的食物不一致，请重新核对目标。"}
        key = f"{type(body).__name__}:{entry_id}:" + body.model_dump_json()
        if key in proposals:
            return proposals[key]
        try:
            service = context.nutrition_service
            if isinstance(body, NutritionSavedEntryRevisionRequest):
                scope = getattr(context, "task_scope", {})
                pending_id = scope.get("confirmation_id") if isinstance(scope, dict) else None
                pending = (
                    await context.confirmation_service.get(
                        user_id=context.user_id, confirmation_id=UUID(str(pending_id))
                    )
                    if pending_id
                    else None
                )
                if pending is not None and pending.status == "pending":
                    card = await service.revise_pending_saved_entry(
                        context.user_id,
                        pending.id,
                        pending.version,
                        entry_id,
                        body,
                    )
                elif pending is not None and pending.status != "succeeded":
                    return {
                        "status": "needs_review",
                        "message": "这份更正草稿已关闭，请重新选择已保存的餐食。",
                    }
                else:
                    card = await service.propose_saved_entry_change(context.user_id, entry_id, body)
            else:
                card = await service.create_entry_delete_confirmation(
                    context.user_id, entry_id, body
                )
        except (
            NutritionNotFoundError,
            NutritionConflictError,
            DatabaseConfirmationNotFoundError,
        ) as exc:
            return {"status": "needs_review", "message": str(exc)}
        payload = {"status": "confirmation_required", "confirmation": confirmation_payload(card)}
        proposals[key] = payload
        return payload

    @tool
    async def propose_saved_meal_update(
        entry_id: UUID, request: NutritionSavedEntryRevisionRequest
    ) -> dict:
        """Draft correcting saved portions, nutrition, or replacing food; approval required.

        First read the exact meal. Each change uses a zero-based item_index from that read.
        Omit foods the user did not ask to change. To replace a food, use
        changes[].replacement with a complete NutritionItemInput, not amount_g/renaming.
        The replacement may use a catalog version or a model_estimated/low estimate
        with an assumed portion and nutrition. The saved original meal is preserved until approval.
        A nutrition_estimate contains ALL FOUR TOTAL nutrients for the resulting
        eaten portion and assumptions, not per-100g values. Only unverified meal-local
        model estimates can be reassessed. Keep amount_g omitted for unchanged portions.
        Catalog/verified nutrients cannot be replaced. Cooking feedback is enough to
        make a tentative estimate; never require the user to calculate fat or oil.
        """
        changes = [
            change.model_copy(update={"replacement": change.replacement.model_copy(update={
                "source": "model_estimated", "confidence": "low",
            })})
            if change.replacement is not None and change.replacement.food_version_id is None
            else change
            for change in request.changes
        ]
        return await propose(entry_id, request.model_copy(update={"changes": changes}))

    @tool
    async def propose_saved_meals_date_change(request: NutritionDateChangeRequest) -> dict:
        """Draft moving saved meals to a corrected date, retaining times and nutrition.

        Read the source day with read_saved_meal_for_change(all_meals=True) first.
        For a single meal use its exact ID. For a whole day include all returned IDs
        and versions, never recreate meals. Approval is required before any date changes.
        """
        if any(read_versions.get(e.entry_id) != e.expected_version for e in request.entries):
            return {"status": "needs_review", "message": "请先读取并核对所有待移动餐食的最新内容。"}
        scope = getattr(context, "task_scope", {})
        bound_id = (
            scope.get("entry_id") or scope.get("meal_id") if isinstance(scope, dict) else None
        )
        if bound_id and {str(e.entry_id) for e in request.entries} != {str(bound_id)}:
            return {"status": "needs_review", "message": "当前只选中了单餐，不能同时移动其他餐食。"}
        key = "date_change:" + request.model_dump_json()
        if key in proposals:
            return proposals[key]
        try:
            replacement = {}
            pending_id = scope.get("confirmation_id") if isinstance(scope, dict) else None
            if pending_id:
                pending = await context.confirmation_service.get(
                    user_id=context.user_id, confirmation_id=UUID(str(pending_id))
                )
                expired = pending.status == "expired" or (
                    pending.status == "pending" and pending.expires_at <= datetime.now(UTC)
                )
                if pending.status == "pending" and not expired:
                    replacement = {"replaces_id": pending.id, "replaces_version": pending.version}
                elif pending.status != "succeeded" and not expired:
                    return {"status": "needs_review", "message": "原草稿已关闭，请重新选择餐食。"}
            card = await context.nutrition_service.propose_saved_date_change(
                context.user_id, request, **replacement
            )
        except (
            NutritionNotFoundError, NutritionConflictError, DatabaseConfirmationNotFoundError
        ) as exc:
            return {"status": "needs_review", "message": str(exc)}
        payload = {"status": "confirmation_required", "confirmation": confirmation_payload(card)}
        proposals[key] = payload
        return payload

    @tool
    async def propose_saved_meal_delete(
        entry_id: UUID, request: NutritionEntryDeleteRequest
    ) -> dict:
        """Draft removing one selected mistaken saved meal from statistics; approval required."""
        return await propose(entry_id, request)

    @tool
    async def propose_saved_meal_item_remove(
        entry_id: UUID,
        item_index: Annotated[int, Field(ge=0)],
        expected_version: Annotated[int, Field(ge=1)],
        reason: Annotated[str, Field(min_length=1, max_length=1000)],
    ) -> dict:
        """Draft removing one food from a saved meal, retaining the other foods; approval required.

        First read the exact meal and resolve its zero-based item_index and latest version.
        Never use this to remove the entire meal. Removing its last food needs explicit
        whole-meal deletion instead. No new meal or food catalog changes are created.
        """
        request = NutritionSavedEntryRevisionRequest(
            expected_version=expected_version,
            remove_item_indices=[item_index],
            reason=reason,
        )
        return await propose(entry_id, request)

    return [
        read_saved_meal_for_change,
        propose_saved_meal_update,
        propose_saved_meal_delete,
        propose_saved_meal_item_remove,
        propose_saved_meals_date_change,
    ]
