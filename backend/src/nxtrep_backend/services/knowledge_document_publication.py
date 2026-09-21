from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from nxtrep_backend.db.models import KnowledgeDocument, KnowledgeSource


class KnowledgePublicationNotFoundError(RuntimeError):
    """发布所需的文档或来源不存在。"""


class KnowledgePublicationConflictError(RuntimeError):
    """文档或来源当前状态不允许发布。"""


class KnowledgePublicationRepository(Protocol):
    async def get_document_by_id(
        self,
        document_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeDocument | None: ...

    async def get_source_by_id(
        self,
        source_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None: ...

    async def list_published_documents(
        self,
        source_id: UUID,
        *,
        exclude_document_id: UUID,
        lock: bool = False,
    ) -> Sequence[KnowledgeDocument]: ...

    async def flush(self) -> None: ...


KnowledgePublicationStatus = Literal["published", "unchanged"]


@dataclass(frozen=True, slots=True)
class KnowledgePublicationResult:
    status: KnowledgePublicationStatus
    document: KnowledgeDocument


class KnowledgeDocumentPublicationService:
    """发布已审核的最新知识文档，并归档旧版本。"""

    def __init__(
        self,
        repository: KnowledgePublicationRepository,
    ) -> None:
        self._repository = repository

    async def publish(
        self,
        document_id: UUID,
        *,
        now: datetime | None = None,
    ) -> KnowledgePublicationResult:
        document = await self._repository.get_document_by_id(
            document_id,
            lock=True,
        )

        if document is None:
            raise KnowledgePublicationNotFoundError("Knowledge document not found")

        source = await self._repository.get_source_by_id(
            document.source_id,
            lock=True,
        )

        if source is None:
            raise KnowledgePublicationNotFoundError("Knowledge source not found")

        if document.review_status == "published":
            if source.is_active:
                return KnowledgePublicationResult(
                    status="unchanged",
                    document=document,
                )

            raise KnowledgePublicationConflictError(
                "Published document belongs to an inactive source"
            )

        if document.review_status != "reviewed":
            raise KnowledgePublicationConflictError(
                "Knowledge document must be reviewed before publication"
            )

        if source.ingest_status != "ready":
            raise KnowledgePublicationConflictError(
                "Knowledge source must be ready before publication"
            )

        if document.source_version != source.latest_version:
            raise KnowledgePublicationConflictError("Knowledge document must be the latest version")

        old_documents = await self._repository.list_published_documents(
            source.id,
            exclude_document_id=document.id,
            lock=True,
        )

        for old_document in old_documents:
            old_document.review_status = "archived"

        document.review_status = "published"
        document.published_at = now or datetime.now(UTC)
        source.is_active = True

        await self._repository.flush()

        return KnowledgePublicationResult(
            status="published",
            document=document,
        )
