from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models.water import WaterEntry


class SqlAlchemyWaterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_entries(self, user_id: UUID, day: date) -> list[WaterEntry]:
        start = datetime.combine(day, time.min, tzinfo=CHINA_TIMEZONE)
        return list(
            await self.session.scalars(
                select(WaterEntry)
                .where(
                    WaterEntry.user_id == user_id,
                    WaterEntry.deleted_at.is_(None),
                    WaterEntry.consumed_at >= start,
                    WaterEntry.consumed_at < start + timedelta(days=1),
                )
                .order_by(WaterEntry.consumed_at.desc())
            )
        )

    async def create(self, user_id: UUID, amount_ml: int, consumed_at: datetime) -> WaterEntry:
        entry = WaterEntry(user_id=user_id, amount_ml=amount_ml, consumed_at=consumed_at)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def delete(self, user_id: UUID, entry_id: UUID) -> bool:
        entry = await self.session.scalar(
            select(WaterEntry)
            .where(
                WaterEntry.id == entry_id,
                WaterEntry.user_id == user_id,
                WaterEntry.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if entry is None:
            return False
        entry.deleted_at = datetime.now(CHINA_TIMEZONE)
        await self.session.flush()
        return True
