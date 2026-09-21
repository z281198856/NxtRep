import os
from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from nxtrep_backend.db.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSource,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.knowledge.schemas import (
    ChunkDraft,
    EmbeddedKnowledgeDocument,
    KnowledgeRetrievalRequest,
    ParsedBlock,
    ParsedDocument,
    PreparedKnowledgeDocument,
)
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.services.knowledge_retrieval import KnowledgeRetrievalService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


@pytest.mark.asyncio
async def test_knowledge_hierarchy_supports_search_vector_cosine_and_cascade() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            source = KnowledgeSource(
                source_key=f"squat-safety-{uuid4().hex}",
                title="深蹲安全指南",
                source_type="manual",
                topic="safety",
                locale="zh-CN",
                ingest_status="ready",
                is_active=True,
                latest_version=1,
            )
            session.add(source)
            await session.flush()

            content = "深蹲时保持脊柱中立，膝盖方向与脚尖一致。"
            document = KnowledgeDocument(
                source_id=source.id,
                source_version=1,
                title=source.title,
                normalized_content=content,
                content_hash=_hash(content),
                topic=source.topic,
                locale=source.locale,
                review_status="reviewed",
            )
            session.add(document)
            await session.flush()

            chunk = KnowledgeChunk(
                document_id=document.id,
                ordinal=0,
                content=content,
                content_hash=_hash(content),
                token_count=18,
                section_path="动作安全/深蹲",
                search_text="深蹲 安全 脊柱 中立 膝盖 脚尖",
            )
            session.add(chunk)
            await session.flush()

            vector = [0.0] * 1024
            vector[0] = 1.0
            embedding = KnowledgeEmbedding(
                chunk_id=chunk.id,
                model_name="embedding-3",
                model_version="2026-09",
                embedding=vector,
                content_hash=chunk.content_hash,
            )
            session.add(embedding)
            await session.flush()

            search_vector_exists = await session.scalar(
                text("SELECT search_vector IS NOT NULL FROM knowledge_chunks WHERE id = :chunk_id"),
                {"chunk_id": chunk.id},
            )
            distance = await session.scalar(
                select(KnowledgeEmbedding.embedding.cosine_distance(vector)).where(
                    KnowledgeEmbedding.id == embedding.id
                )
            )
            assert search_vector_exists is True
            assert distance == pytest.approx(0.0)

            await session.delete(source)
            await session.flush()
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocument)
                    .where(KnowledgeDocument.source_id == source.id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == document.id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeEmbedding)
                    .where(KnowledgeEmbedding.chunk_id == chunk.id)
                )
                == 0
            )
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_knowledge_database_rejects_invalid_activation_and_vector_dimension() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        KnowledgeSource(
                            source_key=f"not-ready-{uuid4().hex}",
                            title="尚未导入",
                            source_type="manual",
                            topic="training",
                            locale="zh-CN",
                            ingest_status="pending",
                            is_active=True,
                        )
                    )
                    await session.flush()

            source = KnowledgeSource(
                source_key=f"test-source-{uuid4().hex}",
                title="测试来源",
                source_type="manual",
                topic="training",
                locale="zh-CN",
                ingest_status="ready",
            )
            session.add(source)
            await session.flush()
            content = "测试内容"
            document = KnowledgeDocument(
                source_id=source.id,
                source_version=1,
                title="测试文档",
                normalized_content=content,
                content_hash=_hash(content),
                topic="training",
                locale="zh-CN",
                review_status="draft",
            )
            session.add(document)
            await session.flush()
            chunk = KnowledgeChunk(
                document_id=document.id,
                ordinal=0,
                content=content,
                content_hash=_hash(content),
                token_count=2,
                search_text="测试 内容",
            )
            session.add(chunk)
            await session.flush()

            with pytest.raises((StatementError, ValueError)):
                async with session.begin_nested():
                    session.add(
                        KnowledgeEmbedding(
                            chunk_id=chunk.id,
                            model_name="embedding-3",
                            model_version="2026-09",
                            embedding=[0.0] * 3,
                            content_hash=chunk.content_hash,
                        )
                    )
                    await session.flush()
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_knowledge_repository_persists_once_and_deduplicates_by_hash() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            source = KnowledgeSource(
                source_key=f"repository-test-{uuid4().hex}",
                title="测试训练指南",
                source_type="file",
                source_uri="raw/test-guide.html",
                topic="training",
                locale="zh-CN",
                ingest_status="pending",
            )
            session.add(source)
            await session.flush()

            content = "训练动作应当循序渐进。"
            content_hash = _hash(content)
            parsed = ParsedDocument(
                source_key="test-training-guide",
                title="测试训练指南",
                topic="training",
                locale="zh-CN",
                blocks=(
                    ParsedBlock(
                        text=content,
                        page_number=1,
                    ),
                ),
                metadata={"normalization_version": "v1"},
            )
            chunk = ChunkDraft(
                ordinal=0,
                content=content,
                content_hash=content_hash,
                token_count=12,
                search_text=content,
                page_numbers=(1,),
                metadata={"chunking_version": "v1"},
            )
            prepared = PreparedKnowledgeDocument(
                document=parsed,
                normalized_content=content,
                content_hash=content_hash,
                chunks=(chunk,),
            )
            vector = tuple([1.0, *([0.0] * 1023)])
            embedded = EmbeddedKnowledgeDocument(
                prepared=prepared,
                model_name="embedding-3",
                model_version="test-v1",
                dimensions=1024,
                vectors=(vector,),
            )
            repository = SqlAlchemyKnowledgeRepository(session)
            ingested_at = datetime(2026, 9, 10, tzinfo=UTC)

            created = await repository.persist_embedded_document(
                source_id=source.id,
                embedded=embedded,
                now=ingested_at,
            )
            unchanged = await repository.persist_embedded_document(
                source_id=source.id,
                embedded=embedded,
                now=ingested_at,
            )

            assert created.status == "created"
            assert created.source_version == 1
            assert created.created_chunks == 1
            assert created.created_embeddings == 1
            assert unchanged.status == "unchanged"
            assert unchanged.document_id == created.document_id
            assert unchanged.source_version == 1
            assert source.latest_version == 1
            assert source.ingest_status == "ready"
            assert source.last_ingested_at == ingested_at
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocument)
                    .where(KnowledgeDocument.source_id == source.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .join(KnowledgeDocument)
                    .where(KnowledgeDocument.source_id == source.id)
                )
                == 1
            )
            stored_chunk = await session.scalar(
                select(KnowledgeChunk)
                .join(KnowledgeDocument)
                .where(KnowledgeDocument.source_id == source.id)
            )
            assert stored_chunk is not None
            assert stored_chunk.metadata_json["page_numbers"] == [1]
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_published_knowledge_supports_live_hybrid_retrieval() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            source = KnowledgeSource(
                source_key=f"hybrid-retrieval-{uuid4().hex}",
                title="深蹲呼吸指南",
                source_type="manual",
                topic="safety",
                locale="zh-CN",
                ingest_status="ready",
                is_active=True,
                latest_version=1,
            )
            session.add(source)
            await session.flush()

            content = "下蹲时吸气并保持躯干稳定，起身通过发力点后呼气。"
            document = KnowledgeDocument(
                source_id=source.id,
                source_version=1,
                title=source.title,
                normalized_content=content,
                content_hash=_hash(content),
                topic=source.topic,
                locale=source.locale,
                review_status="published",
                published_at=datetime.now(UTC),
            )
            session.add(document)
            await session.flush()

            chunk = KnowledgeChunk(
                document_id=document.id,
                ordinal=0,
                content=content,
                content_hash=_hash(content),
                token_count=24,
                section_path="动作要领/呼吸",
                metadata_json={"page_numbers": [4]},
                search_text="squat breathing brace",
            )
            session.add(chunk)
            await session.flush()

            query_vector = [0.0] * 1024
            query_vector[0] = 1.0
            session.add(
                KnowledgeEmbedding(
                    chunk_id=chunk.id,
                    model_name="embedding-3",
                    model_version="test-v1",
                    embedding=query_vector,
                    content_hash=chunk.content_hash,
                )
            )
            await session.flush()

            embeddings = MagicMock()
            embeddings.model_name = "embedding-3"
            embeddings.dimensions = 1024
            embeddings.embed_query = AsyncMock(return_value=query_vector)
            service = KnowledgeRetrievalService(
                repository=SqlAlchemyKnowledgeRepository(session),
                embeddings=embeddings,
                embedding_model_version="test-v1",
            )

            hits = await service.retrieve(
                KnowledgeRetrievalRequest(
                    query="squat breathing",
                    topic="safety",
                    locale="zh-CN",
                    candidate_k=20,
                    top_k=5,
                    source_keys=(source.source_key,),
                )
            )

            assert len(hits) == 1
            assert hits[0].chunk_id == chunk.id
            assert hits[0].source_key == source.source_key
            assert hits[0].source_version == 1
            assert hits[0].match_type == "hybrid"
            assert hits[0].page_numbers == (4,)
            embeddings.embed_query.assert_awaited_once_with("squat breathing")
        finally:
            await transaction.rollback()
