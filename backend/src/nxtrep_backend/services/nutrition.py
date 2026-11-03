import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import (
    Confirmation,
    FlexibleMeal,
    Food,
    FoodVersion,
    NutritionEntry,
    NutritionEntryDraft,
    NutritionEntryRevision,
    NutritionTargetDraft,
    NutritionTargetVersion,
    Recipe,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    CustomFoodDraftRequest,
    CustomFoodPatchRequest,
    DynamicNutritionTargetDraftRequest,
    FlexibleMealCreateRequest,
    FlexibleMealUpdateRequest,
    FoodCreateRequest,
    FoodUpdateRequest,
    NutritionDateChangeRequest,
    NutritionEntryCopyRequest,
    NutritionEntryCreateRequest,
    NutritionEntryDeleteRequest,
    NutritionEntryDraftUpdateRequest,
    NutritionEntryUpdateRequest,
    NutritionEstimateCorrection,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionSavedEntryRevisionRequest,
    NutritionSavedPortionChange,
    NutritionTargetDraftRequest,
    NutritionTextDraftRequest,
    RecipeCreateRequest,
    RecipeUpdateRequest,
)


class NutritionNotFoundError(RuntimeError):
    pass


class NutritionConflictError(RuntimeError):
    def __init__(self, message: str, current_version: int | None = None) -> None:
        super().__init__(message)
        self.current_version = current_version


class NutritionService:
    def __init__(
        self,
        repository: SqlAlchemyNutritionRepository,
        confirmations: SqlAlchemyConfirmationRepository | None = None,
    ) -> None:
        self.repository = repository
        self.confirmations = confirmations

    async def search_foods(
        self,
        *,
        user_id: UUID,
        keyword: str,
        region: str | None = None,
        state: str | None = None,
        page: int = 1,
        page_size: int = 20,
        custom_only: bool = False,
    ) -> tuple[list[tuple[Food, FoodVersion]], int]:
        normalized = keyword.strip()
        if not normalized:
            raise ValueError("keyword must not be blank")
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        options = {"custom_only": True} if custom_only else {}
        return await self.repository.search_foods(
            user_id,
            normalized,
            region,
            state,
            page,
            page_size,
            **options,
        )

    async def list_entries(
        self,
        *,
        user_id: UUID,
        day: date,
        meal_type: str | None = None,
    ) -> list[NutritionEntry]:
        return await self.repository.list_entries(user_id, day, meal_type)

    async def create_food(
        self,
        user_id: UUID,
        body: FoodCreateRequest,
        *,
        source: str = "user_confirmed",
        confidence: str = "high",
    ) -> tuple[Food, FoodVersion]:
        food = Food(
            owner_user_id=user_id,
            name=body.name.strip(),
            brand=body.brand,
            barcode=body.barcode,
        )
        version = FoodVersion(
            food_id=food.id,
            version=1,
            basis_amount_g=body.basis_amount_g,
            kcal=body.kcal,
            protein_g=body.protein_g,
            carbs_g=body.carbs_g,
            fat_g=body.fat_g,
            source=source,
            confidence=confidence,
        )
        await self.repository.add_food(food, version)
        return food, version

    async def propose_custom_food(
        self,
        *,
        user_id: UUID,
        body: CustomFoodDraftRequest,
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="food_create",
                before=None,
                after={"food": body.model_dump(mode="json")},
                reason="用户请求新增个人食品库条目",
                impact=(
                    f"确认后添加到食品库：{body.name}；每 {body.basis_amount_g} 克 "
                    f"{body.kcal} kcal，蛋白质 {body.protein_g} g，"
                    f"碳水 {body.carbs_g} g，脂肪 {body.fat_g} g。{body.notes[:600]}"
                    "不写入任何一餐，也不修改长期记忆。"
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def get_food(self, user_id: UUID, food_id: UUID) -> tuple[Food, FoodVersion]:
        found = await self.repository.get_food(user_id, food_id)
        if found is None:
            raise NutritionNotFoundError("Food not found")
        return found

    async def update_food(
        self,
        user_id: UUID,
        food_id: UUID,
        body: FoodUpdateRequest,
        *,
        source: str = "user_confirmed",
        confidence: str = "high",
    ) -> tuple[Food, FoodVersion]:
        found = await self.repository.get_food(user_id, food_id, custom_only=True, lock=True)
        if found is None:
            raise NutritionNotFoundError("Custom food not found")
        food, current = found
        if current.version != body.expected_version:
            raise NutritionConflictError("Food was modified", current.version)
        food.name = body.name.strip()
        food.brand = body.brand
        food.barcode = body.barcode
        version = FoodVersion(
            food_id=food.id,
            version=current.version + 1,
            basis_amount_g=body.basis_amount_g,
            kcal=body.kcal,
            protein_g=body.protein_g,
            carbs_g=body.carbs_g,
            fat_g=body.fat_g,
            source=source,
            confidence=confidence,
        )
        await self.repository.add_food_version(version)
        return food, version

    async def delete_food(self, user_id: UUID, food_id: UUID, expected_version: int) -> None:
        found = await self.repository.get_food(user_id, food_id, custom_only=True, lock=True)
        if found is None:
            raise NutritionNotFoundError("Custom food not found")
        food, current = found
        if current.version != expected_version:
            raise NutritionConflictError("Food was modified", current.version)
        food.deleted_at = datetime.now(UTC)
        await self.repository.session.flush()

    @staticmethod
    def custom_food_snapshot(food: Food, current: FoodVersion) -> dict:
        return {
            "name": food.name,
            "brand": food.brand,
            "barcode": food.barcode,
            "basis_amount_g": str(current.basis_amount_g),
            "kcal": str(current.kcal),
            "protein_g": str(current.protein_g),
            "carbs_g": str(current.carbs_g),
            "fat_g": str(current.fat_g),
            "source": current.source,
            "confidence": current.confidence,
        }

    async def get_custom_food(self, user_id: UUID, food_id: UUID) -> tuple[Food, FoodVersion]:
        found = await self.repository.get_food(user_id, food_id, custom_only=True)
        if found is None:
            raise NutritionNotFoundError("未找到你的自定义食品；公共食品或其他账户的食品不能修改。")
        return found

    async def propose_custom_food_change(
        self,
        *,
        user_id: UUID,
        food_id: UUID,
        expected_version: int,
        patch: CustomFoodPatchRequest | None = None,
        reason: str = "用户要求删除自定义食品",
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        food, current = await self.get_custom_food(user_id, food_id)
        if current.version != expected_version:
            raise NutritionConflictError(
                "食品已修改，请重新读取最新内容后生成草稿。", current.version
            )
        before = self.custom_food_snapshot(food, current)
        after = {"food_id": str(food.id), "expected_version": current.version}
        operation = "food_delete"
        impact = f"确认后从你的食品库删除“{food.name}”；已保存的饮食记录和营养快照保留。"
        if patch is not None:
            operation = "food_update"
            changes = patch.model_dump(exclude_unset=True, exclude={"notes"})
            updated = {**before, **changes, "notes": patch.notes}
            # Changing the reference grams preserves per-gram nutrition for fields
            # the user did not explicitly change; explicit values use the new basis.
            if patch.basis_amount_g is not None:
                ratio = patch.basis_amount_g / current.basis_amount_g
                for field in ("kcal", "protein_g", "carbs_g", "fat_g"):
                    if field not in patch.model_fields_set:
                        precision = Decimal("0.01") if field == "kcal" else Decimal("0.001")
                        updated[field] = (getattr(current, field) * ratio).quantize(precision)
                updated["notes"] += " 基准克数变化时，未指定营养按原单位克营养同比例换算。"
            if updated.get("source") is None:
                updated["source"] = current.source
            if updated.get("confidence") is None:
                updated["confidence"] = current.confidence
            nutrients = {"kcal", "protein_g", "carbs_g", "fat_g"}
            if current.confidence != "high" and not nutrients <= patch.model_fields_set:
                updated["confidence"] = current.confidence
                updated["source"] = current.source
            body = FoodUpdateRequest.model_validate(
                {
                    **{field: updated[field] for field in FoodCreateRequest.model_fields},
                    "expected_version": current.version,
                }
            )
            after["food"] = {
                **body.model_dump(mode="json", exclude={"expected_version"}),
                "source": updated["source"],
                "confidence": updated["confidence"],
                "notes": updated["notes"],
            }
            reason = patch.notes
            impact = "确认后更新这项自定义食品；只影响以后选用，已保存的饮食记录和营养快照保留。"
        else:
            after["food"] = before
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type=operation,
                before={
                    "food": before,
                    "food_version_id": str(current.id),
                    "version": current.version,
                },
                after=after,
                reason=reason,
                impact=impact,
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def create_entry(
        self, user_id: UUID, body: NutritionEntryCreateRequest
    ) -> NutritionEntry:
        items, totals = await self._snapshot_items(user_id, body.items)
        return await self.repository.add_entry(
            NutritionEntry(
                user_id=user_id,
                meal_type=body.meal_type,
                eaten_at=body.eaten_at,
                items=items,
                totals=totals,
                is_flexible_meal=body.is_flexible_meal,
                notes=body.notes,
            )
        )

    async def copy_entry(
        self, user_id: UUID, entry_id: UUID, body: NutritionEntryCopyRequest
    ) -> NutritionEntry:
        source = await self.repository.get_entry(user_id, entry_id, lock=True)
        if source is None:
            raise NutritionNotFoundError("原餐食记录不存在，请重新选择。")
        if source.version != body.expected_version:
            raise NutritionConflictError("原餐食已更新，请重新选择后复制。", source.version)
        # Preserve the recorded portion and nutrition even if the food catalog has changed.
        return await self.repository.add_entry(NutritionEntry(
            user_id=user_id,
            meal_type=body.meal_type,
            eaten_at=body.eaten_at,
            items=deepcopy(source.items),
            totals=deepcopy(source.totals),
            is_flexible_meal=source.is_flexible_meal,
            notes=source.notes,
        ))

    async def parse_text_draft(
        self, user_id: UUID, body: NutritionTextDraftRequest
    ) -> NutritionEntryDraft:
        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|克)", body.text, re.IGNORECASE)
        amount = Decimal(amount_match.group(1)) if amount_match else Decimal("100")
        candidates, _ = await self.repository.search_foods(
            user_id, body.text.strip(), None, None, 1, 5
        )
        if not candidates:
            for token in re.split(r"[\s,，、;；]+", body.text):
                cleaned = re.sub(r"\d+(?:\.\d+)?(?:g|克)?", "", token).strip()
                if len(cleaned) < 2:
                    continue
                candidates, _ = await self.repository.search_foods(
                    user_id, cleaned, None, None, 1, 5
                )
                if candidates:
                    break
        inputs = (
            [NutritionItemInput(food_version_id=candidates[0][1].id, amount_g=amount)]
            if candidates
            else []
        )
        items, totals = await self._snapshot_items(user_id, inputs)
        missing = [] if items else [body.text]
        questions = [] if items else ["没有匹配到食品，请选择食品并填写实际重量"]
        return await self.repository.add_entry_draft(
            NutritionEntryDraft(
                user_id=user_id,
                original_text=body.text,
                meal_type=body.meal_type,
                eaten_at=body.eaten_at,
                items=items,
                totals=totals,
                missing_items=missing,
                questions=questions,
                is_flexible_meal=body.is_flexible_meal,
                notes=body.notes,
            )
        )

    async def update_entry_draft(
        self,
        user_id: UUID,
        draft_id: UUID,
        body: NutritionEntryDraftUpdateRequest,
    ) -> NutritionEntryDraft:
        item = await self.repository.get_entry_draft(user_id, draft_id, lock=True)
        if item is None:
            raise NutritionNotFoundError("Nutrition entry draft not found")
        if item.version != body.expected_version or item.status != "editing":
            raise NutritionConflictError("Nutrition entry draft was modified", item.version)
        fields = body.model_fields_set - {"expected_version"}
        if "items" in fields and body.items is not None:
            item.items, item.totals = await self._snapshot_items(user_id, body.items)
            item.missing_items = []
            item.questions = []
        for field in fields - {"items"}:
            setattr(item, field, getattr(body, field))
        item.version += 1
        await self.repository.session.flush()
        return item

    async def submit_entry_draft(
        self, user_id: UUID, draft_id: UUID, expected_version: int
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        item = await self.repository.get_entry_draft(user_id, draft_id, lock=True)
        if item is None:
            raise NutritionNotFoundError("Nutrition entry draft not found")
        if item.version != expected_version or item.status != "editing":
            raise NutritionConflictError("Nutrition entry draft was modified", item.version)
        if not item.items or item.missing_items:
            raise NutritionConflictError("Nutrition entry draft is incomplete", item.version)
        entry_items = []
        for row in item.items:
            if row.get("food_version_id"):
                entry_items.append(
                    {"food_version_id": row["food_version_id"], "amount_g": row["amount_g"]}
                )
            else:
                entry_items.append(
                    {
                        key: row[key]
                        for key in (
                            "food_version_id",
                            "amount_g",
                            "name",
                            "basis_amount_g",
                            "kcal",
                            "protein_g",
                            "carbs_g",
                            "fat_g",
                            "source",
                            "confidence",
                        )
                    }
                )
        entry = NutritionEntryCreateRequest(
            meal_type=item.meal_type,
            eaten_at=item.eaten_at,
            items=entry_items,
            is_flexible_meal=item.is_flexible_meal,
            notes=item.notes,
        )
        item.status = "submitted"
        item.version += 1
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_create",
                before=None,
                after={"entry": entry.model_dump(mode="json")},
                reason="用户提交饮食记录草稿",
                impact="确认后写入饮食记录并纳入营养统计",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def propose_entry(
        self,
        *,
        user_id: UUID,
        body: NutritionEntryCreateRequest,
    ) -> Confirmation:
        """Validate a nutrition entry and create a user confirmation."""
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        items, totals = await self._snapshot_items(user_id, body.items)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_create",
                before=None,
                after={
                    "entry": body.model_dump(mode="json"),
                    "preview": {"items": items, "totals": totals},
                },
                reason="用户请求记录一餐饮食",
                impact=(
                    "确认后写入饮食记录；预计总计 "
                    f"{totals['kcal']} kcal，蛋白质 {totals['protein_g']} g，"
                    f"碳水 {totals['carbs_g']} g，脂肪 {totals['fat_g']} g"
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def update_entry(
        self, user_id: UUID, entry_id: UUID, body: NutritionEntryUpdateRequest
    ) -> NutritionEntry:
        entry = await self.repository.get_entry(user_id, entry_id, lock=True)
        if entry is None:
            raise NutritionNotFoundError("Nutrition entry not found")
        if entry.version != body.expected_version:
            raise NutritionConflictError("Nutrition entry was modified", entry.version)
        old = self._entry_snapshot(entry)
        fields = body.model_fields_set - {"reason", "expected_version"}
        if "items" in fields and body.items is not None:
            entry.items, entry.totals = await self._snapshot_items(user_id, body.items)
        for name in fields - {"items"}:
            setattr(entry, name, getattr(body, name))
        entry.version += 1
        new = self._entry_snapshot(entry)
        await self.repository.add_entry_revision(
            NutritionEntryRevision(
                entry_id=entry.id, old_values=old, new_values=new, reason=body.reason
            )
        )
        return entry

    async def get_saved_entry(self, user_id: UUID, entry_id: UUID) -> NutritionEntry:
        entry = await self.repository.get_entry(user_id, entry_id)
        if entry is None:
            raise NutritionNotFoundError("饮食记录不存在、已删除或不属于当前账户。")
        return entry

    @staticmethod
    def _apply_estimate(item: dict, estimate: NutritionEstimateCorrection) -> None:
        # Only a meal-local model estimate may be replaced. Catalog versions and
        # measured/user-confirmed nutrition remain authoritative for portion edits.
        if item.get("food_version_id") or item.get("source") not in {
            "model_estimated",
            "vision_estimate",
        }:
            raise NutritionConflictError(
                "这项食物使用食品库或已核实的营养依据，不能直接调低或调高。"
                "请核对实际份量或具体食品条目；其他模型估算的菜品可以单独重估。"
            )
        try:
            amount = Decimal(str(item["amount_g"]))
            if not amount.is_finite() or amount <= 0:
                raise ValueError
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise NutritionConflictError("原食物份量无效，无法可靠重估；记录未修改。") from exc
        if estimate.protein_g + estimate.carbs_g + estimate.fat_g > amount:
            raise NutritionConflictError("营养重估的三项克数合计超过食物份量，请核对单位。")
        item["basis_amount_g"] = item["amount_g"]
        item.update(
            {key: str(getattr(estimate, key)) for key in ("kcal", "protein_g", "carbs_g", "fat_g")}
        )
        item.update(
            source="model_estimated", confidence="low", estimate_assumptions=estimate.assumptions
        )

    @staticmethod
    def _correct_saved_portions(
        entry: NutritionEntry, body: NutritionSavedEntryRevisionRequest,
        replacements: dict[int, dict] | None = None,
    ):
        items = deepcopy(entry.items)
        keys = ("kcal", "protein_g", "carbs_g", "fat_g")
        removals = set(body.remove_item_indices)
        if any(index >= len(items) for index in removals):
            raise NutritionConflictError("食物位置不在这份记录中，请重新读取核对。")
        if removals and len(removals) == len(items):
            raise NutritionConflictError(
                "移除全部食物会使这餐为空，请明确选择删除整餐；记录未修改。"
            )
        for change in body.changes:
            if change.item_index >= len(items):
                raise NutritionConflictError("食物位置不在这份记录中，请重新读取核对。")
            item = items[change.item_index]
            if change.replacement is not None:
                if not replacements or change.item_index not in replacements:
                    raise NutritionConflictError("替换食物尚未核对营养依据，记录未修改。")
                items[change.item_index] = deepcopy(replacements[change.item_index])
                continue
            if change.nutrition_estimate is not None:
                if change.amount_g is not None:
                    item["amount_g"] = str(change.amount_g)
                NutritionService._apply_estimate(item, change.nutrition_estimate)
                for key in keys:
                    item[f"total_{key}"] = item[key]
                continue
            try:
                old_amount = Decimal(str(item["amount_g"]))
                basis = Decimal(str(item.get("basis_amount_g", 0)))
                if not old_amount.is_finite() or old_amount <= 0:
                    raise ValueError
                for key in keys:
                    # Reuse the saved basis; never read a changed/deleted catalog food.
                    value = (
                        Decimal(str(item[key])) * change.amount_g / basis
                        if basis.is_finite() and basis > 0 and key in item
                        else Decimal(str(item[f"total_{key}"])) * change.amount_g / old_amount
                    )
                    if not value.is_finite() or value < 0:
                        raise ValueError
                    item[f"total_{key}"] = str(value)
                item["amount_g"] = str(change.amount_g)
            except (KeyError, ValueError, ArithmeticError, TypeError) as exc:
                raise NutritionConflictError(
                    "这项食物缺少有效的原份量或营养快照，无法可靠更正；记录未修改。"
                ) from exc
        items = [item for index, item in enumerate(items) if index not in removals]
        try:
            totals = {key: Decimal(0) for key in keys}
            for item in items:
                for key in keys:
                    value = Decimal(str(item[f"total_{key}"]))
                    if not value.is_finite() or value < 0:
                        raise ValueError
                    totals[key] += value
        except (KeyError, ValueError, ArithmeticError, TypeError) as exc:
            raise NutritionConflictError("这餐原营养快照不完整，无法重算；记录未修改。") from exc
        return items, {key: str(value) for key, value in totals.items()}

    async def preview_saved_revision(self, user_id, entry, body):
        """Resolve only replacement foods; all untouched saved snapshots stay intact."""
        replacements = {}
        for change in body.changes:
            if change.replacement is not None:
                snapshots, _ = await self._snapshot_items(user_id, [change.replacement])
                replacements[change.item_index] = snapshots[0]
        return self._correct_saved_portions(entry, body, replacements)

    async def _date_change_entries(
        self, user_id: UUID, body: NutritionDateChangeRequest, *, lock: bool = False
    ) -> list[NutritionEntry]:
        if body.target_date > datetime.now(CHINA_TIMEZONE).date():
            raise NutritionConflictError("已吃下的饮食不能移到未来日期，请核对目标日期。")
        entries = []
        # Lock in a stable order and validate every row before changing any row.
        for expected in sorted(body.entries, key=lambda item: str(item.entry_id)):
            entry = await self.repository.get_entry(user_id, expected.entry_id, lock=lock)
            if entry is None or entry.deleted_at is not None:
                raise NutritionNotFoundError("部分饮食记录不存在、已删除或不属于当前账户。")
            if entry.version != expected.expected_version:
                raise NutritionConflictError("部分餐食已被修改，日期更正尚未执行，请重新核对。")
            if entry.eaten_at.astimezone(CHINA_TIMEZONE).date() != body.source_date:
                raise NutritionConflictError("部分餐食已不在原日期，日期更正尚未执行，请重新核对。")
            entries.append(entry)
        return entries

    async def propose_saved_date_change(
        self, user_id: UUID, body: NutritionDateChangeRequest,
        *, replaces_id: UUID | None = None, replaces_version: int | None = None,
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        old = None
        if replaces_id is not None:
            old = await self.confirmations.get_confirmation(user_id, replaces_id, lock=True)
            if (
                old is None or old.status != "pending" or old.version != replaces_version
                or old.operation_type != "nutrition_entries_date_change"
                or old.expires_at <= datetime.now(UTC)
            ):
                raise NutritionConflictError("原日期更正草稿已变化，请重新核对后生成草稿。")
        entries = await self._date_change_entries(user_id, body)
        entries.sort(key=lambda entry: (entry.eaten_at, str(entry.id)))
        card = await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entries_date_change",
                before={"entries": [deepcopy(self._entry_snapshot(entry)) for entry in entries]},
                after={
                    "request": body.model_dump(mode="json"),
                    "preview": {
                        "source_date": body.source_date.isoformat(),
                        "target_date": body.target_date.isoformat(),
                        "entries": [
                            {
                                "meal_type": entry.meal_type,
                                "time": entry.eaten_at.astimezone(CHINA_TIMEZONE).strftime("%H:%M"),
                                "foods": [item.get("name", "食物") for item in entry.items],
                                "kcal": entry.totals.get("kcal"),
                            }
                            for entry in entries
                        ],
                    },
                },
                reason=body.reason,
                impact=f"确认后将所列{len(entries)}餐从{body.source_date}移至{body.target_date}，"
                "保留原用餐时间、食物、营养和备注，并更新两天的饮食统计。",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        if old is not None:
            card.after = {**card.after, "replaces_confirmation_id": str(old.id)}
            old.after = {**old.after, "replaced_by_confirmation_id": str(card.id)}
            old.status = "cancelled"
            old.version += 1
            await self.repository.session.flush()
        return card

    async def apply_saved_date_change(
        self, user_id: UUID, body: NutritionDateChangeRequest
    ) -> dict:
        entries = await self._date_change_entries(user_id, body, lock=True)
        for entry in entries:
            old = deepcopy(self._entry_snapshot(entry))
            local = entry.eaten_at.astimezone(CHINA_TIMEZONE)
            entry.eaten_at = datetime.combine(
                body.target_date, local.timetz(), tzinfo=CHINA_TIMEZONE
            ).astimezone(UTC)
            entry.version += 1
            self.repository.session.add(
                NutritionEntryRevision(
                    entry_id=entry.id,
                    old_values=old,
                    new_values=deepcopy(self._entry_snapshot(entry)),
                    reason=body.reason,
                )
            )
        await self.repository.session.flush()
        return {
            "success": True,
            "source_date": body.source_date.isoformat(),
            "target_date": body.target_date.isoformat(),
            "entries": [{"entry_id": str(e.id), "version": e.version} for e in entries],
        }

    async def propose_saved_entry_change(
        self, user_id: UUID, entry_id: UUID, body: NutritionSavedEntryRevisionRequest
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        entry = await self.get_saved_entry(user_id, entry_id)
        if entry.version != body.expected_version:
            raise NutritionConflictError("这餐已被修改，请重新读取后生成草稿。", entry.version)
        items, totals = await self.preview_saved_revision(user_id, entry, body)
        preview_items = dict(zip(
            (i for i in range(len(entry.items)) if i not in body.remove_item_indices),
            items, strict=True,
        ))
        preview = {
            "date": entry.eaten_at.astimezone(CHINA_TIMEZONE).date().isoformat(),
            "meal_type": entry.meal_type,
            "eaten_at": entry.eaten_at.astimezone(CHINA_TIMEZONE).isoformat(),
            "changes": [
                {
                    "item_index": c.item_index,
                    "name": entry.items[c.item_index].get("name", "食物"),
                    "old_amount_g": entry.items[c.item_index]["amount_g"],
                    "amount_g": str(c.replacement.amount_g)
                    if c.replacement is not None
                    else str(c.amount_g)
                    if c.amount_g is not None
                    else entry.items[c.item_index]["amount_g"],
                    **({"replacement_name": preview_items[c.item_index]["name"],
                        "estimate_assumptions": preview_items[c.item_index].get(
                            "estimate_assumptions"
                        )}
                       if c.replacement is not None else {}),
                    **(
                        {
                            "nutrition_before": {
                                key: entry.items[c.item_index].get(f"total_{key}")
                                for key in ("kcal", "protein_g", "carbs_g", "fat_g")
                            },
                            "nutrition_after": c.nutrition_estimate.model_dump(
                                mode="json", exclude={"assumptions"}
                            ),
                            "estimate_assumptions": c.nutrition_estimate.assumptions,
                        }
                        if c.nutrition_estimate is not None
                        else {}
                    ),
                }
                for c in body.changes
            ],
            "removed_items": [
                {
                    "item_index": index,
                    "name": entry.items[index].get("name", "食物"),
                    "amount_g": entry.items[index].get("amount_g"),
                }
                for index in body.remove_item_indices
            ],
            "totals_before": deepcopy(entry.totals),
            "totals_after": totals,
        }
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_update",
                before=deepcopy(self._entry_snapshot(entry)),
                after={
                    "entry_id": str(entry_id),
                    "expected_version": entry.version,
                    "changes": body.model_dump(mode="json", exclude_none=True)["changes"],
                    "remove_item_indices": body.remove_item_indices,
                    "preview": preview,
                },
                reason=body.reason,
                impact=(
                    "确认后移除这餐中的"
                    + "、".join(
                        str(entry.items[index].get("name", "食物"))
                        for index in body.remove_item_indices
                    )
                    + ("并更正指定份量" if body.changes else "")
                    + "，保留其他食物、修订历史并更新饮食统计。"
                    if body.remove_item_indices
                    else "确认后按说明的依据重估所选食物营养，保留修订历史并更新饮食统计。"
                    if any(c.nutrition_estimate is not None for c in body.changes)
                    else "确认后替换指定食物，保留其他食物、修订历史并更新饮食统计。"
                    if any(c.replacement is not None for c in body.changes)
                    else (
                        "确认后仅更正所选食物份量，沿用原营养依据，"
                        "保留修订历史并更新饮食统计；其他餐食和食品库不变。"
                    )
                ),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def revise_pending_saved_entry(
        self,
        user_id: UUID,
        confirmation_id: UUID,
        expected_confirmation_version: int,
        entry_id: UUID,
        body: NutritionSavedEntryRevisionRequest,
    ) -> Confirmation:
        """Patch the pending correction, retaining prior edits until one final approval."""
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        old = await self.confirmations.get_confirmation(user_id, confirmation_id, lock=True)
        if old is None:
            raise NutritionNotFoundError("未找到这份待确认的餐食更正草稿。")
        if (
            old.operation_type != "nutrition_entry_update"
            or old.status != "pending"
            or old.version != expected_confirmation_version
            or old.expires_at <= datetime.now(UTC)
            or old.after.get("entry_id") != str(entry_id)
            or old.after.get("expected_version") != body.expected_version
        ):
            raise NutritionConflictError("餐食或更正草稿已变化，请重新读取核对。")
        entry = await self.get_saved_entry(user_id, entry_id)
        previous = NutritionSavedEntryRevisionRequest.model_validate(
            {
                "expected_version": old.after["expected_version"],
                "changes": old.after.get("changes", []),
                "remove_item_indices": old.after.get("remove_item_indices", []),
                "reason": old.reason or "修订餐食草稿",
            }
        )
        changes = {change.item_index: change for change in previous.changes}
        removed = set(previous.remove_item_indices)
        for change in body.changes:
            if change.item_index in removed:
                raise NutritionConflictError(
                    "这项食物在待确认草稿中已被移除，请先取消该草稿再重新选择。"
                )
            prior = changes.get(change.item_index)
            data = prior.model_dump(exclude_none=True) if prior else {}
            if change.replacement is not None:
                data = {"item_index": change.item_index}
            elif prior and prior.replacement is not None:
                if change.nutrition_estimate is not None:
                    raise NutritionConflictError("替换后的食物需要先确认，再重估其营养。")
                replacement = prior.replacement.model_dump()
                replacement["amount_g"] = change.amount_g
                data["replacement"] = replacement
                changes[change.item_index] = NutritionSavedPortionChange.model_validate(data)
                continue
            data.update(change.model_dump(exclude_none=True))
            if (
                prior
                and prior.nutrition_estimate is not None
                and change.amount_g is not None
                and change.nutrition_estimate is None
            ):
                old_amount = prior.amount_g or Decimal(
                    str(entry.items[change.item_index]["amount_g"])
                )
                ratio = change.amount_g / old_amount
                estimate = prior.nutrition_estimate.model_dump()
                for key in ("kcal", "protein_g", "carbs_g", "fat_g"):
                    estimate[key] = (estimate[key] * ratio).quantize(Decimal("0.001"))
                data["nutrition_estimate"] = estimate
            changes[change.item_index] = NutritionSavedPortionChange.model_validate(data)
        removed.update(body.remove_item_indices)
        combined = NutritionSavedEntryRevisionRequest(
            expected_version=body.expected_version,
            changes=[change for index, change in changes.items() if index not in removed],
            remove_item_indices=sorted(removed),
            reason=body.reason,
        )
        revised = await self.propose_saved_entry_change(user_id, entry_id, combined)
        revised.after = {**revised.after, "replaces_confirmation_id": str(old.id)}
        old.status, old.version = "rejected", old.version + 1
        old.after = {**old.after, "replaced_by_confirmation_id": str(revised.id)}
        await self.repository.session.flush()
        return revised

    async def correct_saved_entry(
        self, user_id: UUID, entry_id: UUID, body: NutritionSavedEntryRevisionRequest
    ) -> NutritionEntry:
        entry = await self.repository.get_entry(user_id, entry_id, lock=True)
        if entry is None or entry.version != body.expected_version:
            raise NutritionConflictError("这餐已更改或删除，旧草稿未生效，请重新读取核对。")
        items, totals = await self.preview_saved_revision(user_id, entry, body)
        old = deepcopy(self._entry_snapshot(entry))
        entry.items, entry.totals = items, totals
        entry.version += 1
        await self.repository.add_entry_revision(
            NutritionEntryRevision(
                entry_id=entry.id,
                old_values=old,
                new_values=deepcopy(self._entry_snapshot(entry)),
                reason=body.reason,
            )
        )
        return entry

    async def revise_pending_entry(
        self, user_id: UUID, confirmation_id: UUID, body: NutritionPendingEntryRevisionRequest
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        old = await self.confirmations.get_confirmation(user_id, confirmation_id, lock=True)
        if old is None:
            raise NutritionNotFoundError("Pending meal not found")
        if (
            old.operation_type != "nutrition_entry_create"
            or old.status != "pending"
            or old.version != body.expected_version
            or old.expires_at <= datetime.now(UTC)
        ):
            raise NutritionConflictError("Meal draft changed or is no longer pending", old.version)
        entry = NutritionEntryCreateRequest.model_validate(old.after["entry"])
        if any(index >= len(entry.items) for index in body.remove_item_indices):
            raise NutritionConflictError("食物位置不在这份草稿中，请重新读取。")
        for change in body.changes:
            if change.item_index >= len(entry.items):
                raise NutritionConflictError("Meal item index is outside the draft")
            item = entry.items[change.item_index]
            if change.replacement is not None:
                entry.items[change.item_index] = change.replacement.model_copy(deep=True)
                continue
            if change.name and change.name != item.name and (
                item.food_version_id is not None or change.nutrition_estimate is None
            ):
                raise NutritionConflictError(
                    "换食物需要完整replacement（新食物及其份量、营养依据），不能只改名称沿用原营养。"
                )
            # Keep the original nutrient basis. Only the eaten grams change;
            # custom totals normalized on creation must not be multiplied twice.
            if change.amount_g is not None:
                item.amount_g = change.amount_g
            if change.nutrition_estimate is not None:
                data = item.model_dump(mode="json")
                self._apply_estimate(data, change.nutrition_estimate)
                item = NutritionItemInput.model_validate(data)
                entry.items[change.item_index] = item
            if change.name and item.food_version_id is None:
                item.name = change.name
        entry.items = [item for index, item in enumerate(entry.items)
                       if index not in body.remove_item_indices]
        entry.items.extend(item.model_copy(deep=True) for item in body.additions)
        if not entry.items:
            raise NutritionConflictError("移除全部食物请取消这份草稿；原草稿仍然有效。")
        if body.notes is not None:
            entry.notes = body.notes
        # Validate/recalculate before invalidating the old card. Both changes
        # share the same request transaction and lock as approval.
        revised = await self.propose_entry(user_id=user_id, body=entry)
        revised.after = {**revised.after, "replaces_confirmation_id": str(old.id)}
        revised.before = old.after
        revised.reason = "用户修订未确认饮食草稿的份量或营养估算"
        old.status = "rejected"
        old.version += 1
        old.after = {**old.after, "replaced_by_confirmation_id": str(revised.id)}
        await self.repository.session.flush()
        return revised

    async def create_entry_delete_confirmation(
        self,
        user_id: UUID,
        entry_id: UUID,
        body: NutritionEntryDeleteRequest,
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        entry = await self.repository.get_entry(user_id, entry_id)
        if entry is None:
            raise NutritionNotFoundError("饮食记录不存在、已删除或不属于当前账户。")
        if entry.version != body.expected_version:
            raise NutritionConflictError("这餐已被修改，请重新读取后生成草稿。", entry.version)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_delete",
                before=self._entry_snapshot(entry),
                after={
                    "entry_id": str(entry.id),
                    "expected_version": entry.version,
                    "preview": {
                        "date": entry.eaten_at.astimezone(CHINA_TIMEZONE).date().isoformat(),
                        "meal_type": entry.meal_type,
                        "eaten_at": entry.eaten_at.astimezone(CHINA_TIMEZONE).isoformat(),
                        "items": deepcopy(entry.items),
                        "totals_before": deepcopy(entry.totals),
                        "totals_after": {
                            key: "0" for key in ("kcal", "protein_g", "carbs_g", "fat_g")
                        },
                    },
                },
                reason=body.reason,
                impact="确认后该饮食记录从统计中移除，修订历史保留",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def delete_entry(
        self,
        user_id: UUID,
        entry_id: UUID,
        expected_version: int,
        reason: str = "用户确认删除饮食记录",
    ) -> dict:
        entry = await self.repository.get_entry(user_id, entry_id, lock=True)
        if entry is None or entry.version != expected_version:
            raise NutritionConflictError("这餐已更改或删除，旧草稿未生效，请重新读取核对。")
        old = deepcopy(self._entry_snapshot(entry))
        old["deleted_at"] = None
        entry.deleted_at = datetime.now(UTC)
        entry.version += 1
        new = deepcopy(self._entry_snapshot(entry))
        new["deleted_at"] = entry.deleted_at.isoformat()
        await self.repository.add_entry_revision(
            NutritionEntryRevision(
                entry_id=entry.id,
                old_values=old,
                new_values=new,
                reason=reason,
            )
        )
        return {"resource_id": str(entry.id), "resource_version": entry.version}

    async def daily_summary(self, user_id: UUID, day: date) -> dict:
        entries = await self.repository.list_entries(user_id, day)
        consumed = {key: Decimal("0") for key in ("kcal", "protein_g", "carbs_g", "fat_g")}
        for entry in entries:
            for key in consumed:
                consumed[key] += Decimal(str(entry.totals[key]))
        target = await self.repository.get_active_target(user_id, day)
        target_values = target.values if target else None
        remaining = None
        if target_values:
            remaining = {}
            for key, consumed_key in (
                ("kcal", "kcal"),
                ("protein", "protein_g"),
                ("carbs", "carbs_g"),
                ("fat", "fat_g"),
            ):
                for bound in ("min", "max"):
                    target_key = f"{key}_{bound}" + ("_g" if key != "kcal" else "")
                    remaining[target_key] = str(
                        max(
                            Decimal(str(target_values[target_key])) - consumed[consumed_key],
                            Decimal("0"),
                        )
                    )
        recorded_types = {entry.meal_type for entry in entries}
        recorded_meals = [
            meal for meal in ("breakfast", "lunch", "dinner") if meal in recorded_types
        ]
        completeness = Decimal(len(recorded_meals)) / Decimal("3")
        return {
            "date": day,
            "target": target_values,
            "consumed": consumed,
            "remaining": remaining,
            "record_completeness": completeness.quantize(Decimal("0.01")),
            "recorded_meals": recorded_meals,
        }

    async def preview_meal_option(
        self, user_id: UUID, day: date, items: list[NutritionItemInput]
    ) -> dict:
        """Calculate an unsaved meal against the actual daily target and records."""
        if not 1 <= len(items) <= 50:
            raise ValueError("一餐建议需要 1 到 50 项食物")
        snapshots, totals = await self._snapshot_items(user_id, items)
        summary = await self.daily_summary(user_id, day)
        after = {
            key: str(Decimal(str(summary["consumed"][key])) + Decimal(value))
            for key, value in totals.items()
        }
        balance = None
        if summary["target"]:
            balance = {}
            for key, value in after.items():
                prefix = key.removesuffix("_g")
                suffix = "_g" if key != "kcal" else ""
                for bound in ("min", "max"):
                    target_key = f"{prefix}_{bound}{suffix}"
                    balance[target_key] = str(
                        Decimal(str(summary["target"][target_key])) - Decimal(value)
                    )
        return {
            "saved": False,
            "summary": summary,
            "items": snapshots,
            "meal_totals": totals,
            "projected_consumed": after,
            "remaining_after_meal": balance,
            "limitations": [
                "这是一餐建议的估算，没有写入饮食记录。",
                "负余量表示超过目标范围；未记录的进食未计入。",
                "自定义食物的营养估算存在份量、配方和烹饪差异。",
            ],
        }

    async def weekly_summary(self, user_id: UUID, start_date: date) -> dict:
        end_date = start_date + timedelta(days=6)
        entries = await self.repository.list_entries_range(user_id, start_date, end_date)
        totals = {key: Decimal("0") for key in ("kcal", "protein_g", "carbs_g", "fat_g")}
        days: set[date] = set()
        flexible_count = 0
        for entry in entries:
            days.add(entry.eaten_at.astimezone(CHINA_TIMEZONE).date())
            flexible_count += int(entry.is_flexible_meal)
            for key in totals:
                totals[key] += Decimal(str(entry.totals[key]))
        divisor = Decimal(len(days) or 1)
        average = {
            key: (value / divisor).quantize(Decimal("0.01")) for key, value in totals.items()
        }
        return {
            "start_date": start_date,
            "end_date": end_date,
            "daily_average": average,
            "total_entries": len(entries),
            "recorded_days": len(days),
            "flexible_meals": flexible_count,
            "record_completeness": (Decimal(len(days)) / Decimal("7")).quantize(Decimal("0.01")),
        }

    async def nutrition_advice(self, user_id: UUID, food_name: str, day: date) -> dict:
        summary = await self.daily_summary(user_id, day)
        remaining = summary["remaining"]
        cautions = []
        if remaining is None:
            recommendation = "可以记录这份食物，但尚未设置营养目标，无法判断合适份量。"
            cautions.append("先设置热量和宏量营养目标可获得更准确建议")
        else:
            kcal_max = Decimal(str(remaining.get("kcal_max", 0)))
            recommendation = (
                f"可以纳入当天饮食；当前目标上限约还剩 {kcal_max} kcal，"
                "请按实际重量记录并结合蛋白质、碳水和脂肪余量调整份量。"
            )
        return {
            "food_name": food_name,
            "recommendation": recommendation,
            "remaining": remaining,
            "cautions": cautions,
        }

    async def create_flexible_meal(
        self, user_id: UUID, body: FlexibleMealCreateRequest
    ) -> FlexibleMeal:
        existing = await self.repository.list_flexible_meals(
            user_id, body.scheduled_date, body.scheduled_date
        )
        if existing:
            raise NutritionConflictError("A flexible meal is already planned for this date")
        return await self.repository.add_flexible_meal(
            FlexibleMeal(user_id=user_id, **body.model_dump())
        )

    async def update_flexible_meal(
        self,
        user_id: UUID,
        item_id: UUID,
        body: FlexibleMealUpdateRequest,
    ) -> FlexibleMeal:
        item = await self.repository.get_flexible_meal(user_id, item_id, lock=True)
        if item is None:
            raise NutritionNotFoundError("Flexible meal not found")
        if item.version != body.expected_version:
            raise NutritionConflictError("Flexible meal was modified", item.version)
        fields = body.model_fields_set - {"expected_version"}
        if "scheduled_date" in fields and body.scheduled_date != item.scheduled_date:
            existing = await self.repository.list_flexible_meals(
                user_id, body.scheduled_date, body.scheduled_date
            )
            if existing:
                raise NutritionConflictError("A flexible meal is already planned for this date")
        for field in fields:
            setattr(item, field, getattr(body, field))
        item.version += 1
        await self.repository.session.flush()
        return item

    async def create_target_draft(
        self, user_id: UUID, body: NutritionTargetDraftRequest
    ) -> NutritionTargetDraft:
        return await self.repository.add_target_draft(
            NutritionTargetDraft(user_id=user_id, **body.model_dump())
        )

    async def create_dynamic_target_draft(
        self, user_id: UUID, body: DynamicNutritionTargetDraftRequest
    ) -> NutritionTargetDraft:
        end_date = body.effective_from - timedelta(days=1)
        start_date = end_date - timedelta(days=13)
        entries = await self.repository.list_entries_range(user_id, start_date, end_date)
        recorded_days = {item.eaten_at.astimezone(CHINA_TIMEZONE).date() for item in entries}
        if len(recorded_days) < 14:
            raise NutritionConflictError(
                "At least 14 complete days of nutrition records are required"
            )
        current = await self.repository.get_active_target(user_id, end_date)
        if current is None:
            raise NutritionConflictError("An active nutrition target is required")
        factor = {
            "decrease": Decimal("0.95"),
            "maintain": Decimal("1.00"),
            "increase": Decimal("1.05"),
        }[body.desired_direction]
        values = current.values

        def adjusted(name: str) -> Decimal:
            return (Decimal(str(values[name])) * factor).quantize(Decimal("0.01"))

        return await self.create_target_draft(
            user_id,
            NutritionTargetDraftRequest(
                effective_from=body.effective_from,
                kcal_min=adjusted("kcal_min"),
                kcal_max=adjusted("kcal_max"),
                protein_min_g=adjusted("protein_min_g"),
                protein_max_g=adjusted("protein_max_g"),
                carbs_min_g=adjusted("carbs_min_g"),
                carbs_max_g=adjusted("carbs_max_g"),
                fat_min_g=adjusted("fat_min_g"),
                fat_max_g=adjusted("fat_max_g"),
            ),
        )

    async def create_recipe(self, user_id: UUID, body: RecipeCreateRequest) -> Recipe:
        items, totals = await self._snapshot_items(user_id, body.items)
        return await self.repository.add_recipe(
            Recipe(
                user_id=user_id,
                name=body.name.strip(),
                servings=body.servings,
                items=items,
                totals=totals,
                notes=body.notes,
            )
        )

    async def update_recipe(
        self, user_id: UUID, recipe_id: UUID, body: RecipeUpdateRequest
    ) -> Recipe:
        item = await self.repository.get_recipe(user_id, recipe_id, lock=True)
        if item is None:
            raise NutritionNotFoundError("Recipe not found")
        if item.version != body.expected_version:
            raise NutritionConflictError("Recipe was modified", item.version)
        if "name" in body.model_fields_set:
            item.name = body.name.strip()
        if "servings" in body.model_fields_set:
            item.servings = body.servings
        if "notes" in body.model_fields_set:
            item.notes = body.notes
        if body.items is not None:
            item.items, item.totals = await self._snapshot_items(user_id, body.items)
        item.version += 1
        await self.repository.session.flush()
        return item

    async def delete_recipe(self, user_id: UUID, recipe_id: UUID, expected_version: int) -> None:
        item = await self.repository.get_recipe(user_id, recipe_id, lock=True)
        if item is None:
            raise NutritionNotFoundError("Recipe not found")
        if item.version != expected_version:
            raise NutritionConflictError("Recipe was modified", item.version)
        item.deleted_at = datetime.now(UTC)
        item.version += 1
        await self.repository.session.flush()

    async def submit_target(
        self, user_id: UUID, target_id: UUID, expected_version: int
    ) -> Confirmation:
        if self.confirmations is None:
            raise RuntimeError("Confirmation repository is required")
        draft = await self.repository.get_target_draft(user_id, target_id, lock=True)
        if draft is None:
            raise NutritionNotFoundError("Nutrition target draft not found")
        if draft.version != expected_version or draft.status != "editing":
            raise NutritionConflictError("Nutrition target draft was modified", draft.version)
        draft.status = "submitted"
        draft.version += 1
        active_target = await self.repository.get_active_target(user_id)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_target_activate",
                before=None,
                after={
                    "target_id": str(draft.id),
                    "draft_version": draft.version,
                    "base_target_version_id": (str(active_target.id) if active_target else None),
                },
                reason="用户提交新的营养目标",
                impact="确认后新目标生效，旧目标保留为历史版本",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def activate_target(
        self,
        user_id: UUID,
        draft_id: UUID,
        draft_version: int,
        base_target_version_id: UUID | None,
    ) -> dict:
        draft = await self.repository.get_target_draft(user_id, draft_id, lock=True)
        if draft is None or draft.version != draft_version or draft.status != "submitted":
            raise NutritionConflictError("Nutrition target changed before approval")
        current = await self.repository.get_active_target(user_id)
        if (current.id if current else None) != base_target_version_id:
            raise NutritionConflictError("Active nutrition target changed before approval")
        if current:
            current.status = "superseded"
            target_id = current.target_id
            version_number = current.version + 1
            await self.repository.session.flush()
        else:
            target_id = uuid4()
            version_number = 1
        values = {
            name: str(getattr(draft, name))
            for name in (
                "kcal_min",
                "kcal_max",
                "protein_min_g",
                "protein_max_g",
                "carbs_min_g",
                "carbs_max_g",
                "fat_min_g",
                "fat_max_g",
            )
        }
        await self.repository.add_target_version(
            NutritionTargetVersion(
                target_id=target_id,
                user_id=user_id,
                source_draft_id=draft.id,
                effective_from=draft.effective_from,
                values=values,
                version=version_number,
                status="active",
            )
        )
        return {"resource_id": str(target_id), "resource_version": version_number}

    async def _snapshot_items(
        self, user_id: UUID, items: list[NutritionItemInput]
    ) -> tuple[list[dict], dict]:
        snapshots: list[dict] = []
        totals = {key: Decimal("0") for key in ("kcal", "protein_g", "carbs_g", "fat_g")}
        for item in items:
            if item.food_version_id:
                found = await self.repository.get_food_version(user_id, item.food_version_id)
                if found is None:
                    raise NutritionNotFoundError(f"Food version {item.food_version_id} not found")
                food, version = found
                source = {
                    "food_version_id": str(version.id),
                    "name": food.name,
                    "basis_amount_g": version.basis_amount_g,
                    "kcal": version.kcal,
                    "protein_g": version.protein_g,
                    "carbs_g": version.carbs_g,
                    "fat_g": version.fat_g,
                    "source": version.source,
                    "confidence": version.confidence,
                }
            else:
                source = item.model_dump(exclude_none=True)
                source["food_version_id"] = None
            ratio = item.amount_g / Decimal(str(source["basis_amount_g"]))
            snapshot = {
                key: (str(value) if isinstance(value, Decimal) else value)
                for key, value in source.items()
            }
            snapshot["amount_g"] = str(item.amount_g)
            for key in totals:
                value = Decimal(str(source[key])) * ratio
                totals[key] += value
                snapshot[f"total_{key}"] = str(value)
            snapshots.append(snapshot)
        return snapshots, {key: str(value) for key, value in totals.items()}

    @staticmethod
    def _entry_snapshot(entry: NutritionEntry) -> dict:
        return {
            "meal_type": entry.meal_type,
            "eaten_at": entry.eaten_at.isoformat(),
            "items": entry.items,
            "totals": entry.totals,
            "is_flexible_meal": entry.is_flexible_meal,
            "notes": entry.notes,
            "version": entry.version,
        }
