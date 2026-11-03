from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.context import AgentToolContext


def build_web_tools(context: AgentToolContext) -> list[BaseTool]:
    service = context.web_search_service
    if service is None:
        return []

    @tool
    async def search_web(query: str, domain: str | None = None, refresh: bool = False) -> dict:
        """Search public training, nutrition and recovery knowledge. No personal data in query.

        Prefer brand official domains or research/health authorities. Results are search
        excerpts with real URLs, not verified complete pages.
        Use refresh=True for latest/live requests.
        Cached evidence keeps its original searched_at; do not claim a fresh search.
        At most three searches per request.
        """
        if refresh:
            return await service.search(query, domain, refresh=True)
        return await service.search(query, domain)

    return [search_web]
