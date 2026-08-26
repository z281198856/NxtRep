from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    Food,
    FoodVersion,
    NutritionEntry,
    NutritionEntryRevision,
    NutritionTargetDraft,
    NutritionTargetVersion,
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
            or_(Food.owner_user_id.is_(None), Food.owner_user_id == user_id),
            or_(Food.name.ilike(f"%{keyword}%"), Food.brand.ilike(f"%{keyword}%")),
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

    async def add_food(self, food: Food, version: FoodVersion) -> None:
        self.session.add(food)
        await self.session.flush()
        version.food_id = food.id
        self.session.add(version)
        await self.session.flush()

    async def get_food_version(self, version_id: UUID) -> tuple[Food, FoodVersion] | None:
        row = (
            await self.session.execute(
                select(Food, FoodVersion)
                .join(FoodVersion, FoodVersion.food_id == Food.id)
                .where(FoodVersion.id == version_id)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def add_entry(self, entry: NutritionEntry) -> NutritionEntry:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_entry(
        self, user_id: UUID, entry_id: UUID, *, lock: bool = False
    ) -> NutritionEntry | None:
        statement = select(NutritionEntry).where(
            NutritionEntry.id == entry_id, NutritionEntry.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list_entries(
        self, user_id: UUID, day: date, meal_type: str | None = None
    ) -> list[NutritionEntry]:
        start = datetime.combine(day, time.min).astimezone()
        end = datetime.combine(day, time.max).astimezone()
        conditions = [
            NutritionEntry.user_id == user_id,
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
        conditions = [
            NutritionTargetVersion.user_id == user_id,
            NutritionTargetVersion.status == "active",
        ]
        if on_date:
            conditions.append(NutritionTargetVersion.effective_from <= on_date)
        return await self.session.scalar(select(NutritionTargetVersion).where(*conditions))

    async def add_target_version(self, target: NutritionTargetVersion) -> None:
        self.session.add(target)
        await self.session.flush()
