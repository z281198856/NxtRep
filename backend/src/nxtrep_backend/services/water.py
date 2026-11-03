from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import Confirmation
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.water import SqlAlchemyWaterRepository
from nxtrep_backend.schemas.water import WaterEntryCreateRequest


class WaterService:
    def __init__(
        self, repository: SqlAlchemyWaterRepository, confirmations: SqlAlchemyConfirmationRepository
    ) -> None:
        self.repository = repository
        self.confirmations = confirmations

    async def summary(self, user_id: UUID, day: date) -> dict:
        entries = await self.repository.list_entries(user_id, day)
        return {
            "date": day.isoformat(),
            "water_ml": sum(entry.amount_ml for entry in entries),
            "entries": [
                {
                    "id": str(entry.id),
                    "amount_ml": entry.amount_ml,
                    "consumed_at": entry.consumed_at.isoformat(),
                }
                for entry in entries
            ],
        }

    async def propose_entry(self, user_id: UUID, body: WaterEntryCreateRequest) -> Confirmation:
        day = body.consumed_at.astimezone(CHINA_TIMEZONE).date().isoformat()
        return await self.confirmations.add_confirmation(
            Confirmation(
                user_id=user_id,
                operation_type="water_entry_create",
                before=None,
                after={"water": body.model_dump(mode="json")},
                reason="用户请求记录饮水",
                impact=f"确认后计入 {day} 的饮水记录：{body.amount_ml} ml。",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
