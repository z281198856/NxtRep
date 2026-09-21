from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from nxtrep_backend.db.models import KnowledgeDocument


class KnowledgeDocumentNotFoundError(RuntimeError):
    """需要审核的知识文档不存在。"""


class KnowledgeDocumentReviewConflictError(RuntimeError):
    """知识文档当前状态不允许审核。"""


class KnowledgeDocumentReviewRepository(Protocol):
    async def get_document_by_id(
        self,
        document_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeDocument | None: ...

    async def flush(self) -> None: ...


KnowledgeDocumentReviewStatus = Literal["reviewed", "unchanged"]


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentReviewResult:
    status: KnowledgeDocumentReviewStatus
    document: KnowledgeDocument


class KnowledgeDocumentReviewService:
    """审核已经完成摄取的知识文档。"""

    def __init__(
        self,
        repository: KnowledgeDocumentReviewRepository,
    ) -> None:
        self._repository = repository

    async def review(
        self,
        document_id: UUID,
    ) -> KnowledgeDocumentReviewResult:
        document = await self._repository.get_document_by_id(
            document_id,
            lock=True,
        )

        if document is None:
            raise KnowledgeDocumentNotFoundError("Knowledge document not found")

        if document.review_status == "reviewed":
            return KnowledgeDocumentReviewResult(
                status="unchanged",
                document=document,
            )

        if document.review_status != "draft":
            raise KnowledgeDocumentReviewConflictError(
                f"Knowledge document with status {document.review_status!r} cannot be reviewed"
            )

        document.review_status = "reviewed"
        await self._repository.flush()

        return KnowledgeDocumentReviewResult(
            status="reviewed",
            document=document,
        )
