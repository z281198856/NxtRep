from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import (
    FlexibleMeal,
    Food,
    FoodAlias,
    FoodVersion,
    NutritionEntry,
    NutritionEntryDraft,
    NutritionEntryRevision,
    NutritionTargetDraft,
    NutritionTargetVersion,
    Recipe,
)


class SqlAlchemyNutritionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_foods(
        self,
        user_id: UUID,
        keyword: str,
        region: str | None,
        state: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Food, FoodVersion]], int]:
        latest = (
            select(FoodVersion.food_id, func.max(FoodVersion.version).label("version"))
            .group_by(FoodVersion.food_id)
            .subquery()
        )
        conditions = [
            Food.deleted_at.is_(None),
            or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id),
            or_(
                Food.name.ilike(f"%{keyword}%"),
                Food.brand.ilike(f"%{keyword}%"),
                Food.id.in_(select(FoodAlias.food_id).where(FoodAlias.alias.ilike(f"%{keyword}%"))),
            ),
        ]
        if region:
            conditions.append(Food.region == region)
        if state:
            conditions.append(Food.state == state)
        base = (
            select(Food, FoodVersion)
            .join(latest, latest.c.food_id == Food.id)
            .join(
                FoodVersion,
                (FoodVersion.food_id == latest.c.food_id)
                & (FoodVersion.version == latest.c.version),
            )
            .where(*conditions)
        )
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (
            await self.session.execute(
                base.order_by(Food.name).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return [(row[0], row[1]) for row in rows], int(total or 0)

    async def find_foods_by_exact_alias(
        self,
        *,
        user_id: UUID,
        alias: str,
    ) -> list[tuple[Food, FoodVersion]]:
        latest = (
            select(FoodVersion.food_id, func.max(FoodVersion.version).label("version"))
            .group_by(FoodVersion.food_id)
            .subquery()
        )
        aliased_food_ids = select(FoodAlias.food_id).where(
            func.lower(func.btrim(FoodAlias.alias)) == alias.strip().lower()
        )
        rows = (
            await self.session.execute(
                select(Food, FoodVersion)
                .join(latest, latest.c.food_id == Food.id)
                .join(
                    FoodVersion,
                    (FoodVersion.food_id == latest.c.food_id)
                    & (FoodVersion.version == latest.c.version),
                )
                .where(
                    Food.deleted_at.is_(None),
                    or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id),
                    Food.id.in_(aliased_food_ids),
                )
                .order_by(Food.name)
                .limit(5)
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def add_food(self, food: Food, version: FoodVersion) -> None:
        self.session.add(food)
        await self.session.flush()
        version.food_id = food.id
        self.session.add(version)
        await self.session.flush()

    async def get_food_version(
        self, user_id: UUID, version_id: UUID
    ) -> tuple[Food, FoodVersion] | None:
        row = (
            await self.session.execute(
                select(Food, FoodVersion)
                .join(FoodVersion, FoodVersion.food_id == Food.id)
                .where(
                    FoodVersion.id == version_id,
                    Food.deleted_at.is_(None),
                    or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id),
                )
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def get_food_by_barcode(
        self, user_id: UUID, barcode: str
    ) -> tuple[Food, FoodVersion] | None:
        food = await self.session.scalar(
            select(Food).where(
                Food.barcode == barcode,
                Food.deleted_at.is_(None),
                or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id),
            )
        )
        if food is None:
            return None
        version = await self.session.scalar(
            select(FoodVersion)
            .where(FoodVersion.food_id == food.id)
            .order_by(FoodVersion.version.desc())
            .limit(1)
        )
        return (food, version) if version is not None else None

    async def get_food(
        self,
        user_id: UUID,
        food_id: UUID,
        *,
        custom_only: bool = False,
        lock: bool = False,
    ) -> tuple[Food, FoodVersion] | None:
        conditions = [Food.id == food_id, Food.deleted_at.is_(None)]
        if custom_only:
            conditions.append(Food.owner_user_id == user_id)
        else:
            conditions.append(or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id))
        statement = select(Food).where(*conditions).order_by(Food.id)
        if lock:
            statement = statement.with_for_update()
        food = await self.session.scalar(statement)
        if food is None:
            return None
        version = await self.session.scalar(
            select(FoodVersion)
            .where(FoodVersion.food_id == food.id)
            .order_by(FoodVersion.version.desc())
            .limit(1)
        )
        return (food, version) if version is not None else None

    async def add_food_version(self, version: FoodVersion) -> FoodVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def list_frequent_foods(
        self,
        user_id: UUID,
        *,
        limit: int,
    ) -> list[tuple[Food, FoodVersion, int]]:
        entries = list(
            await self.session.scalars(
                select(NutritionEntry).where(
                    NutritionEntry.user_id == user_id,
                    NutritionEntry.deleted_at.is_(None),
                )
            )
        )
        counts: dict[UUID, int] = {}
        for entry in entries:
            for item in entry.items:
                raw_id = item.get("food_version_id")
                if raw_id:
                    version_id = UUID(str(raw_id))
                    counts[version_id] = counts.get(version_id, 0) + 1
        rows: list[tuple[Food, FoodVersion, int]] = []
        for version_id, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True):
            found = await self.get_food_version(user_id, version_id)
            if found is not None:
                rows.append((found[0], found[1], count))
            if len(rows) >= limit:
                break
        return rows

    async def add_entry(self, entry: NutritionEntry) -> NutritionEntry:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def add_entry_draft(self, item: NutritionEntryDraft) -> NutritionEntryDraft:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_entry_draft(
        self, user_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> NutritionEntryDraft | None:
        statement = select(NutritionEntryDraft).where(
            NutritionEntryDraft.id == draft_id,
            NutritionEntryDraft.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_entry(
        self, user_id: UUID, entry_id: UUID, *, lock: bool = False
    ) -> NutritionEntry | None:
        statement = select(NutritionEntry).where(
            NutritionEntry.id == entry_id,
            NutritionEntry.user_id == user_id,
            NutritionEntry.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_entries(
        self, user_id: UUID, day: date, meal_type: str | None = None
    ) -> list[NutritionEntry]:
        start = datetime.combine(day, time.min, tzinfo=CHINA_TIMEZONE)
        end = datetime.combine(day, time.max, tzinfo=CHINA_TIMEZONE)
        conditions = [
            NutritionEntry.user_id == user_id,
            NutritionEntry.deleted_at.is_(None),
            NutritionEntry.eaten_at >= start,
            NutritionEntry.eaten_at <= end,
        ]
        if meal_type:
            conditions.append(NutritionEntry.meal_type == meal_type)
        return list(
            await self.session.scalars(
                select(NutritionEntry).where(*conditions).order_by(NutritionEntry.eaten_at)
            )
        )

    async def add_entry_revision(self, revision: NutritionEntryRevision) -> None:
        self.session.add(revision)
        await self.session.flush()

    async def list_entries_range(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[NutritionEntry]:
        start = datetime.combine(start_date, time.min, tzinfo=CHINA_TIMEZONE)
        end = datetime.combine(end_date, time.max, tzinfo=CHINA_TIMEZONE)
        return list(
            await self.session.scalars(
                select(NutritionEntry)
                .where(
                    NutritionEntry.user_id == user_id,
                    NutritionEntry.deleted_at.is_(None),
                    NutritionEntry.eaten_at >= start,
                    NutritionEntry.eaten_at <= end,
                )
                .order_by(NutritionEntry.eaten_at)
            )
        )

    async def add_target_draft(self, draft: NutritionTargetDraft) -> NutritionTargetDraft:
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def get_target_draft(
        self, user_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> NutritionTargetDraft | None:
        statement = select(NutritionTargetDraft).where(
            NutritionTargetDraft.id == draft_id, NutritionTargetDraft.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_active_target(
        self, user_id: UUID, on_date: date | None = None
    ) -> NutritionTargetVersion | None:
        conditions = [NutritionTargetVersion.user_id == user_id]
        if on_date:
            conditions.append(NutritionTargetVersion.effective_from <= on_date)
        else:
            conditions.append(NutritionTargetVersion.status == "active")
        return await self.session.scalar(
            select(NutritionTargetVersion)
            .where(*conditions)
            .order_by(
                NutritionTargetVersion.effective_from.desc(),
                NutritionTargetVersion.version.desc(),
            )
            .limit(1)
        )

    async def add_target_version(self, target: NutritionTargetVersion) -> None:
        self.session.add(target)
        await self.session.flush()

    async def list_target_versions(self, user_id: UUID) -> list[NutritionTargetVersion]:
        return list(
            await self.session.scalars(
                select(NutritionTargetVersion)
                .where(NutritionTargetVersion.user_id == user_id)
                .order_by(
                    NutritionTargetVersion.effective_from.desc(),
                    NutritionTargetVersion.version.desc(),
                )
            )
        )

    async def list_flexible_meals(
        self,
        user_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FlexibleMeal]:
        conditions = [FlexibleMeal.user_id == user_id]
        if start_date:
            conditions.append(FlexibleMeal.scheduled_date >= start_date)
        if end_date:
            conditions.append(FlexibleMeal.scheduled_date <= end_date)
        return list(
            await self.session.scalars(
                select(FlexibleMeal).where(*conditions).order_by(FlexibleMeal.scheduled_date)
            )
        )

    async def add_flexible_meal(self, item: FlexibleMeal) -> FlexibleMeal:
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_flexible_meal(
        self,
        user_id: UUID,
        item_id: UUID,
        *,
        lock: bool = False,
    ) -> FlexibleMeal | None:
        statement = select(FlexibleMeal).where(
            FlexibleMeal.id == item_id,
            FlexibleMeal.user_id == user_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def add_recipe(self, item: Recipe) -> Recipe:
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_recipes(
        self, user_id: UUID, page: int, page_size: int
    ) -> tuple[list[Recipe], int]:
        conditions = [Recipe.user_id == user_id, Recipe.deleted_at.is_(None)]
        total = await self.session.scalar(
            select(func.count()).select_from(Recipe).where(*conditions)
        )
        items = list(
            await self.session.scalars(
                select(Recipe)
                .where(*conditions)
                .order_by(Recipe.name, Recipe.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total or 0)

    async def get_recipe(
        self, user_id: UUID, recipe_id: UUID, *, lock: bool = False
    ) -> Recipe | None:
        statement = select(Recipe).where(
            Recipe.id == recipe_id,
            Recipe.user_id == user_id,
            Recipe.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
