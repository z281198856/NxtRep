from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nxtrep_backend.db.models import (
    Confirmation,
    Food,
    FoodVersion,
    NutritionEntry,
    NutritionEntryRevision,
    NutritionTargetDraft,
    NutritionTargetVersion,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    FoodCreateRequest,
    NutritionEntryCreateRequest,
    NutritionEntryUpdateRequest,
    NutritionItemInput,
    NutritionTargetDraftRequest,
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

    async def create_food(self, user_id: UUID, body: FoodCreateRequest) -> tuple[Food, FoodVersion]:
        food = Food(owner_user_id=user_id, name=body.name.strip(), brand=body.brand)
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

    async def create_target_draft(
        self, user_id: UUID, body: NutritionTargetDraftRequest
    ) -> NutritionTargetDraft:
        return await self.repository.add_target_draft(
            NutritionTargetDraft(user_id=user_id, **body.model_dump())
        )

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
                    "base_target_version_id": (
                        str(active_target.id) if active_target else None
                    ),
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
