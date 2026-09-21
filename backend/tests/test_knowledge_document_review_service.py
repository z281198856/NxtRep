from uuid import UUID, uuid4

import pytest

from nxtrep_backend.db.models import KnowledgeDocument
from nxtrep_backend.services.knowledge_document_review import (
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentReviewConflictError,
    KnowledgeDocumentReviewResult,
    KnowledgeDocumentReviewService,
)


class FakeKnowledgeDocumentReviewRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, KnowledgeDocument] = {}
        self.lock_values: list[bool] = []
        self.flush_count = 0

    async def get_document_by_id(
        self,
        document_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeDocument | None:
        self.lock_values.append(lock)
        return self.documents.get(document_id)

    async def flush(self) -> None:
        self.flush_count += 1


def build_document(*, review_status: str) -> KnowledgeDocument:
    document = KnowledgeDocument(
        source_id=uuid4(),
        source_version=1,
        title="全民健身指南",
        normalized_content="每天保持适量运动。",
        content_hash="a" * 64,
        topic="training",
        locale="zh-CN",
        review_status=review_status,
        metadata_json={},
    )
    document.id = uuid4()
    return document


@pytest.mark.asyncio
async def test_review_changes_draft_document_to_reviewed() -> None:
    repository = FakeKnowledgeDocumentReviewRepository()
    document = build_document(review_status="draft")
    repository.documents[document.id] = document

    result = await KnowledgeDocumentReviewService(repository).review(document.id)

    assert isinstance(result, KnowledgeDocumentReviewResult)
    assert result.status == "reviewed"
    assert result.document is document
    assert document.review_status == "reviewed"
    assert repository.lock_values == [True]
    assert repository.flush_count == 1


@pytest.mark.asyncio
async def test_review_is_idempotent_for_reviewed_document() -> None:
    repository = FakeKnowledgeDocumentReviewRepository()
    document = build_document(review_status="reviewed")
    repository.documents[document.id] = document

    result = await KnowledgeDocumentReviewService(repository).review(document.id)

    assert result.status == "unchanged"
    assert document.review_status == "reviewed"
    assert repository.lock_values == [True]
    assert repository.flush_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("review_status", ["published", "archived"])
async def test_review_rejects_document_that_cannot_return_to_reviewed(
    review_status: str,
) -> None:
    repository = FakeKnowledgeDocumentReviewRepository()
    document = build_document(review_status=review_status)
    repository.documents[document.id] = document

    with pytest.raises(
        KnowledgeDocumentReviewConflictError,
        match="cannot be reviewed",
    ):
        await KnowledgeDocumentReviewService(repository).review(document.id)

    assert document.review_status == review_status
    assert repository.flush_count == 0


@pytest.mark.asyncio
async def test_review_rejects_missing_document() -> None:
    repository = FakeKnowledgeDocumentReviewRepository()

    with pytest.raises(
        KnowledgeDocumentNotFoundError,
        match="not found",
    ):
        await KnowledgeDocumentReviewService(repository).review(uuid4())

    assert repository.lock_values == [True]
    assert repository.flush_count == 0
