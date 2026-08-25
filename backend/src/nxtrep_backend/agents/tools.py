from uuid import UUID

from langchain.tools import tool


def build_read_tools(user_id: UUID) -> list:
    """Build request-scoped tools so every future query retains the user boundary."""

    @tool
    async def get_current_user_context() -> str:
        """Read the minimum profile and current goal needed for this answer."""
        # TODO: call a repository whose query always includes this bound user_id.
        return f"user_id={user_id}; profile provider is not implemented yet"

    @tool
    async def get_recent_training_summary(days: int = 14) -> str:
        """Read this user's recent training summary for the requested number of days."""
        safe_days = min(max(days, 1), 90)
        # TODO: return aggregate data, not unrestricted raw records.
        return f"user_id={user_id}; days={safe_days}; training provider is not implemented yet"

    return [get_current_user_context, get_recent_training_summary]
