from datetime import date

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.services.coaching_review import build_progress_review


def build_review_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_progress_review(start_date: date, end_date: date) -> dict:
        """Read a personal training/nutrition/body/recovery review and equal-length prior period.

        This queries actual records for at most 92 days; it does not alter plans or targets.
        Nutrition averages only describe logged intake, not total real food intake.
        """
        if not 1 <= (end_date - start_date).days + 1 <= 92:
            raise ValueError("聊天复盘日期须为不超过 92 天的连续区间")
        review = await build_progress_review(
            context.body_service, context.user_id, start_date, end_date
        )
        return {"status": "available", "period": review["period"], "summary": json_safe(review)}

    return [read_progress_review]
