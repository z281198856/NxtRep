from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
)
from nxtrep_backend.knowledge.schemas import KnowledgeRetrievalRequest
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository


def build_published_hierarchy() -> tuple[
    KnowledgeSource,
    KnowledgeDocument,
    KnowledgeChunk,
]:
    source = KnowledgeSource(
        id=uuid4(),
        source_key="official-guide",
        title="全民健身指南",
        source_type="url",
        source_uri="https://www.sport.gov.cn/guide",
        topic="exercise",
        locale="zh-CN",
        ingest_status="ready",
        is_active=True,
        latest_version=2,
    )
    document = KnowledgeDocument(
        id=uuid4(),
        source_id=source.id,
        source_version=2,
        title="全民健身指南 v2",
        normalized_content="每天保持适量运动。",
        content_hash="b" * 64,
        topic="exercise",
        locale="zh-CN",
        review_status="published",
        published_at=datetime.now(UTC),
        metadata_json={},
    )
    chunk = KnowledgeChunk(
        id=uuid4(),
        document_id=document.id,
        ordinal=0,
        content="下蹲时保持膝盖与脚尖方向一致。",
        content_hash="c" * 64,
        token_count=12,
        section_path="力量训练 > 深蹲",
        metadata_json={
            "page_numbers": [12, 13],
            "audience": "adult",
        },
        search_text="力量训练 深蹲 下蹲时保持膝盖与脚尖方向一致",
    )
    return source, document, chunk


def build_request() -> KnowledgeRetrievalRequest:
    return KnowledgeRetrievalRequest(
        query="深蹲膝盖方向",
        topic="exercise",
        locale="zh-CN",
        candidate_k=20,
        top_k=5,
        source_keys=("official-guide",),
    )


@pytest.mark.asyncio
async def test_full_text_search_filters_published_scope_and_maps_citation() -> None:
    source, document, chunk = build_published_hierarchy()
    query_result = MagicMock()
    query_result.all.return_value = [
        (chunk, document, source, 0.75),
    ]
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=query_result)
    repository = SqlAlchemyKnowledgeRepository(session)

    hits = await repository.search_full_text(build_request())

    assert len(hits) == 1
    hit = hits[0]
    assert hit.chunk_id == chunk.id
    assert hit.document_id == document.id
    assert hit.source_id == source.id
    assert hit.source_key == source.source_key
    assert hit.source_title == source.title
    assert hit.source_uri == source.source_uri
    assert hit.source_version == document.source_version
    assert hit.content == chunk.content
    assert hit.section_path == chunk.section_path
    assert hit.page_numbers == (12, 13)
    assert hit.score == 0.75
    assert hit.match_type == "full_text"
    assert hit.metadata["audience"] == "adult"

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    compiled_statement = str(compiled)
    parameter_values = tuple(compiled.params.values())
    assert "JOIN knowledge_documents" in compiled_statement
    assert "JOIN knowledge_sources" in compiled_statement
    assert "knowledge_sources.is_active IS true" in compiled_statement
    assert "knowledge_sources.ingest_status =" in compiled_statement
    assert "knowledge_documents.review_status =" in compiled_statement
    assert "knowledge_documents.topic =" in compiled_statement
    assert "knowledge_documents.locale =" in compiled_statement
    assert "knowledge_sources.source_key IN" in compiled_statement
    assert "websearch_to_tsquery" in compiled_statement
    assert "knowledge_chunks.search_vector @@" in compiled_statement
    assert "LIMIT" in compiled_statement
    assert "simple" in parameter_values
    assert "深蹲膝盖方向" in parameter_values
    assert "ready" in parameter_values
    assert "published" in parameter_values
    assert "exercise" in parameter_values
    assert "zh-CN" in parameter_values
    assert any(
        value in {("official-guide",), "official-guide"}
        if isinstance(value, (str, tuple))
        else value == ["official-guide"]
        for value in parameter_values
    )
    assert 20 in parameter_values


@pytest.mark.asyncio
async def test_vector_search_filters_embedding_identity_and_maps_citation() -> None:
    source, document, chunk = build_published_hierarchy()
    query_result = MagicMock()
    query_result.all.return_value = [
        (chunk, document, source, 0.88),
    ]
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=query_result)
    repository = SqlAlchemyKnowledgeRepository(session)
    query_vector = (0.1,) * 1024

    hits = await repository.search_vector(
        build_request(),
        query_vector=query_vector,
        model_name="embedding-3",
        model_version="v1",
        dimensions=1024,
    )

    assert len(hits) == 1
    hit = hits[0]
    assert hit.chunk_id == chunk.id
    assert hit.source_key == source.source_key
    assert hit.source_version == document.source_version
    assert hit.page_numbers == (12, 13)
    assert hit.score == 0.88
    assert hit.match_type == "vector"

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    compiled_statement = str(compiled)
    parameter_values = tuple(compiled.params.values())
    assert "FROM knowledge_embeddings" in compiled_statement
    assert "JOIN knowledge_chunks" in compiled_statement
    assert "JOIN knowledge_documents" in compiled_statement
    assert "JOIN knowledge_sources" in compiled_statement
    assert "knowledge_embeddings.embedding <=>" in compiled_statement
    assert "knowledge_embeddings.model_name =" in compiled_statement
    assert "knowledge_embeddings.model_version =" in compiled_statement
    assert "knowledge_embeddings.dimensions =" in compiled_statement
    assert "knowledge_sources.is_active IS true" in compiled_statement
    assert "knowledge_sources.ingest_status =" in compiled_statement
    assert "knowledge_documents.review_status =" in compiled_statement
    assert "knowledge_documents.topic =" in compiled_statement
    assert "knowledge_documents.locale =" in compiled_statement
    assert "knowledge_sources.source_key IN" in compiled_statement
    assert "embedding-3" in parameter_values
    assert "v1" in parameter_values
    assert 1024 in parameter_values
    assert 20 in parameter_values


@pytest.mark.asyncio
async def test_vector_search_rejects_query_vector_dimension_mismatch() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    repository = SqlAlchemyKnowledgeRepository(session)

    with pytest.raises(ValueError, match="query vector dimension"):
        await repository.search_vector(
            build_request(),
            query_vector=(0.1, 0.2),
            model_name="embedding-3",
            model_version="v1",
            dimensions=1024,
        )

    session.execute.assert_not_awaited()
