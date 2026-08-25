from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConfirmationNotFoundError(LookupError):
    pass


class ConfirmationAlreadyDecidedError(RuntimeError):
    pass


@dataclass(slots=True)
class ConfirmationDraft:
    user_id: UUID
    operation: str
    after: dict[str, Any]
    reason: str
    impact: str
    before: dict[str, Any] | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None

    def decide(self, decision: str) -> None:
        if self.status is not ConfirmationStatus.PENDING:
            raise ConfirmationAlreadyDecidedError(f"Confirmation {self.id} is already decided")
        self.status = (
            ConfirmationStatus.APPROVED if decision == "approve" else ConfirmationStatus.REJECTED
        )
        self.decided_at = datetime.now(UTC)
