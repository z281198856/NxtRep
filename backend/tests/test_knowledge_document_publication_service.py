from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nxtrep_backend.db.models import KnowledgeDocument, KnowledgeSource
from nxtrep_backend.services.knowledge_document_publication import (
    KnowledgeDocumentPublicationService,
    KnowledgePublicationConflictError,
    KnowledgePublicationNotFoundError,
    KnowledgePublicationResult,
)


class FakeKnowledgePublicationRepository:
    def __init__(self) -> None:
        self.sources: dict[UUID, KnowledgeSource] = {}
        self.documents: dict[UUID, KnowledgeDocument] = {}
        self.document_lock_values: list[bool] = []
        self.source_lock_values: list[bool] = []
        self.list_calls: list[tuple[UUID, UUID, bool]] = []
        self.flush_count = 0

    async def get_document_by_id(
        self,
        document_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeDocument | None:
        self.document_lock_values.append(lock)
        return self.documents.get(document_id)

    async def get_source_by_id(
        self,
        source_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None:
        self.source_lock_values.append(lock)
        return self.sources.get(source_id)

    async def list_published_documents(
        self,
        source_id: UUID,
        *,
        exclude_document_id: UUID,
        lock: bool = False,
    ) -> list[KnowledgeDocument]:
        self.list_calls.append((source_id, exclude_document_id, lock))
        return [
            document
            for document in self.documents.values()
            if document.source_id == source_id
            and document.id != exclude_document_id
            and document.review_status == "published"
        ]

    async def flush(self) -> None:
        self.flush_count += 1


def build_source(
    *,
    ingest_status: str = "ready",
    is_active: bool = False,
    latest_version: int = 2,
) -> KnowledgeSource:
    source = KnowledgeSource(
        source_key="national-fitness-guide",
        title="全民健身指南",
        source_type="url",
        source_uri="https://www.sport.gov.cn/guide",
        topic="training",
        locale="zh-CN",
        ingest_status=ingest_status,
        is_active=is_active,
        latest_version=latest_version,
    )
    source.id = uuid4()
    return source


def build_document(
    source: KnowledgeSource,
    *,
    source_version: int,
    review_status: str,
    published_at: datetime | None = None,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        source_id=source.id,
        source_version=source_version,
        title=f"全民健身指南 v{source_version}",
        normalized_content="每天保持适量运动。",
        content_hash=str(source_version) * 64,
        topic="training",
        locale="zh-CN",
        review_status=review_status,
        published_at=published_at,
        metadata_json={},
    )
    document.id = uuid4()
    return document


@pytest.mark.asyncio
async def test_publish_archives_old_version_and_activates_source() -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source()
    old_published_at = datetime.now(UTC) - timedelta(days=30)
    old_document = build_document(
        source,
        source_version=1,
        review_status="published",
        published_at=old_published_at,
    )
    target = build_document(
        source,
        source_version=2,
        review_status="reviewed",
    )
    repository.sources[source.id] = source
    repository.documents = {
        old_document.id: old_document,
        target.id: target,
    }
    published_at = datetime.now(UTC)

    result = await KnowledgeDocumentPublicationService(repository).publish(
        target.id,
        now=published_at,
    )

    assert isinstance(result, KnowledgePublicationResult)
    assert result.status == "published"
    assert result.document is target
    assert target.review_status == "published"
    assert target.published_at == published_at
    assert old_document.review_status == "archived"
    assert old_document.published_at == old_published_at
    assert source.is_active is True
    assert repository.document_lock_values == [True]
    assert repository.source_lock_values == [True]
    assert repository.list_calls == [(source.id, target.id, True)]
    assert repository.flush_count == 1


@pytest.mark.asyncio
async def test_publish_is_idempotent_for_active_published_document() -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source(is_active=True)
    document = build_document(
        source,
        source_version=2,
        review_status="published",
        published_at=datetime.now(UTC),
    )
    repository.sources[source.id] = source
    repository.documents[document.id] = document

    result = await KnowledgeDocumentPublicationService(repository).publish(
        document.id
    )

    assert result.status == "unchanged"
    assert repository.list_calls == []
    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_publish_rejects_missing_document() -> None:
    repository = FakeKnowledgePublicationRepository()

    with pytest.raises(KnowledgePublicationNotFoundError, match="not found"):
        await KnowledgeDocumentPublicationService(repository).publish(uuid4())

    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_publish_rejects_missing_source() -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source()
    document = build_document(
        source,
        source_version=2,
        review_status="reviewed",
    )
    repository.documents[document.id] = document

    with pytest.raises(KnowledgePublicationNotFoundError, match="not found"):
        await KnowledgeDocumentPublicationService(repository).publish(document.id)

    assert repository.flush_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("review_status", ["draft", "archived"])
async def test_publish_requires_reviewed_document(review_status: str) -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source()
    document = build_document(
        source,
        source_version=2,
        review_status=review_status,
    )
    repository.sources[source.id] = source
    repository.documents[document.id] = document

    with pytest.raises(
        KnowledgePublicationConflictError,
        match="must be reviewed",
    ):
        await KnowledgeDocumentPublicationService(repository).publish(document.id)

    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_publish_requires_ready_source() -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source(ingest_status="processing")
    document = build_document(
        source,
        source_version=2,
        review_status="reviewed",
    )
    repository.sources[source.id] = source
    repository.documents[document.id] = document

    with pytest.raises(
        KnowledgePublicationConflictError,
        match="source must be ready",
    ):
        await KnowledgeDocumentPublicationService(repository).publish(document.id)

    assert source.is_active is False
    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_publish_requires_latest_source_version() -> None:
    repository = FakeKnowledgePublicationRepository()
    source = build_source(latest_version=2)
    document = build_document(
        source,
        source_version=1,
        review_status="reviewed",
    )
    repository.sources[source.id] = source
    repository.documents[document.id] = document

    with pytest.raises(
        KnowledgePublicationConflictError,
        match="latest version",
    ):
        await KnowledgeDocumentPublicationService(repository).publish(document.id)

    assert repository.flush_count == 0
