from typing import Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationNotFoundError,
)


def build_confirmation_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_confirmation_status(confirmation_id: UUID) -> dict:
        """Read one confirmation's current status and impact."""
        try:
            item = await context.confirmation_service.get(
                user_id=context.user_id,
                confirmation_id=confirmation_id,
            )
        except DatabaseConfirmationNotFoundError:
            return {"status": "not_found", "message": "Confirmation not found."}
        return {"status": "available", "confirmation": confirmation_payload(item)}

    @tool
    async def list_confirmations(
        status: Literal[
            "pending",
            "succeeded",
            "rejected",
            "failed",
            "expired",
            "cancelled",
        ]
        | None = None,
        limit: int = 10,
    ) -> dict:
        """List the user's recent confirmation cards."""
        safe_limit = min(max(limit, 1), 50)
        items, total = await context.confirmation_service.list(
            context.user_id,
            status,
            1,
            safe_limit,
        )
        return {
            "status": "available",
            "total": total,
            "has_more": safe_limit < total,
            "confirmations": [confirmation_payload(item) for item in items],
        }

    return [read_confirmation_status, list_confirmations]


def build_confirmation_cancel_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def cancel_confirmation(confirmation_id: UUID, expected_version: int) -> dict:
        """Cancel an identified pending draft only when the user explicitly requests it.

        Read current confirmation ID/version first. Never approves or reverses an
        already executed operation. Clarify which draft if the reference is ambiguous.
        Deferring approval (先别保存/先不确认/等会再记) does not cancel a draft;
        keep it pending, especially when the user interrupts with a read-only question.
        """
        item = await context.confirmation_service.get(
            user_id=context.user_id, confirmation_id=confirmation_id
        )
        if item.status != "cancelled":
            item = await context.confirmation_service.cancel(
                context.user_id, confirmation_id, expected_version
            )
        return {"status": "cancelled", "confirmation": confirmation_payload(item)}

    return [cancel_confirmation]
