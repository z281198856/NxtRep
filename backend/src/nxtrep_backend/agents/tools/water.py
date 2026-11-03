from datetime import date
from typing import Annotated

from langchain.tools import tool
from pydantic import AwareDatetime, Field

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.water import WaterEntryCreateRequest


def build_water_read_tools(context: AgentToolContext):
    @tool
    async def read_water_entries(day: date) -> dict:
        """Read saved drinking-water amounts and total for a Shanghai calendar day."""
        if context.water_service is None:
            return {"status": "unavailable", "message": "饮水记录暂时不可用。"}
        return {"status": "available", **await context.water_service.summary(context.user_id, day)}

    return [read_water_entries]


def build_water_draft_tools(context: AgentToolContext):
    @tool
    async def propose_water_entry(
        amount_ml: Annotated[int, Field(strict=True, ge=1, le=5000)],
        consumed_at: AwareDatetime,
    ) -> dict:
        """Propose water logging for explicit millilitres; writes only after user confirmation.

        Never guess the size of a cup/bottle. Ask for ml when unknown. Use the user's
        stated date; if omitted use today from context_hints. Do not log a goal, a
        question, a hypothetical, or a caloric drink as drinking water.
        """
        if context.water_service is None:
            return {"status": "unavailable", "message": "饮水记录暂时不可用。"}
        body = WaterEntryCreateRequest(amount_ml=amount_ml, consumed_at=consumed_at)
        confirmation = await context.water_service.propose_entry(context.user_id, body)
        return {
            "status": "confirmation_required",
            "confirmation": confirmation_payload(confirmation),
        }

    return [propose_water_entry]
