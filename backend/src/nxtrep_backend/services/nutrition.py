import re
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
    DynamicNutritionTargetDraftRequest,
    FlexibleMealCreateRequest,
    FlexibleMealUpdateRequest,
    FoodCreateRequest,
    FoodUpdateRequest,
    NutritionEntryCreateRequest,
    NutritionEntryDeleteRequest,
    NutritionEntryDraftUpdateRequest,
    NutritionEntryUpdateRequest,
    NutritionItemInput,
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
    ) -> tuple[list[tuple[Food, FoodVersion]], int]:
        normalized = keyword.strip()
        if not normalized:
            raise ValueError("keyword must not be blank")
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        return await self.repository.search_foods(
            user_id,
            normalized,
            region,
            state,
            page,
            page_size,
        )

    async def list_entries(
        self,
        *,
        user_id: UUID,
        day: date,
        meal_type: str | None = None,
    ) -> list[NutritionEntry]:
        return await self.repository.list_entries(user_id, day, meal_type)

    async def create_food(self, user_id: UUID, body: FoodCreateRequest) -> tuple[Food, FoodVersion]:
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
            source="user_confirmed",
            confidence="high",
        )
        await self.repository.add_food(food, version)
        return food, version

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
            source="user_confirmed",
            confidence="high",
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
        _, totals = await self._snapshot_items(user_id, body.items)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_create",
                before=None,
                after={"entry": body.model_dump(mode="json")},
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
            raise NutritionNotFoundError("Nutrition entry not found")
        if entry.version != body.expected_version:
            raise NutritionConflictError("Nutrition entry was modified", entry.version)
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="nutrition_entry_delete",
                before=self._entry_snapshot(entry),
                after={
                    "entry_id": str(entry.id),
                    "expected_version": entry.version,
                },
                reason=body.reason,
                impact="确认后该饮食记录从统计中移除，修订历史保留",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )

    async def delete_entry(self, user_id: UUID, entry_id: UUID, expected_version: int) -> dict:
        entry = await self.repository.get_entry(user_id, entry_id, lock=True)
        if entry is None or entry.version != expected_version:
            raise NutritionConflictError("Nutrition entry changed before approval")
        entry.deleted_at = datetime.now(UTC)
        entry.version += 1
        await self.repository.session.flush()
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
        completeness = min(Decimal(len(entries)) / Decimal("3"), Decimal("1"))
        return {
            "date": day,
            "target": target_values,
            "consumed": consumed,
            "remaining": remaining,
            "record_completeness": completeness.quantize(Decimal("0.01")),
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
