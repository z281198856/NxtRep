from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSource,
)
from nxtrep_backend.knowledge.schemas import (
    EmbeddedKnowledgeDocument,
    KnowledgeMatchType,
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)


class KnowledgeSourceNotFoundError(RuntimeError):
    """请求摄取的知识来源不存在。"""


class KnowledgeSourceMetadataMismatchError(RuntimeError):
    """导入文件的主题或语言与数据库来源不一致。"""


@dataclass(frozen=True, slots=True)
class KnowledgePersistenceResult:
    status: Literal["created", "unchanged"]
    source_id: UUID
    document_id: UUID
    source_version: int
    created_chunks: int
    created_embeddings: int


class SqlAlchemyKnowledgeRepository:
    """以一个数据库事务保存文档、切片、向量和来源状态。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_source_by_key(
        self,
        source_key: str,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None:
        statement = select(KnowledgeSource).where(KnowledgeSource.source_key == source_key)
        if lock:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def add_source(
        self,
        source: KnowledgeSource,
    ) -> KnowledgeSource:
        self._session.add(source)
        await self._session.flush()
        return source

    async def list_sources(self, page: int, page_size: int) -> tuple[list[KnowledgeSource], int]:
        total = int(
            await self._session.scalar(select(func.count()).select_from(KnowledgeSource)) or 0
        )
        items = list(
            await self._session.scalars(
                select(KnowledgeSource)
                .order_by(KnowledgeSource.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    async def delete_source(self, source: KnowledgeSource) -> None:
        await self._session.delete(source)
        await self._session.flush()

    async def get_document_by_id(
        self,
        document_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)

        if lock:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def flush(self) -> None:
        await self._session.flush()

    async def persist_embedded_document(
        self,
        *,
        source_id: UUID,
        embedded: EmbeddedKnowledgeDocument,
        now: datetime | None = None,
    ) -> KnowledgePersistenceResult:
        source = await self._session.scalar(
            select(KnowledgeSource).where(KnowledgeSource.id == source_id).with_for_update()
        )

        if source is None:
            raise KnowledgeSourceNotFoundError("Knowledge source not found")

        self._validate_source_metadata(source, embedded)

        existing = await self._session.scalar(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.content_hash == embedded.prepared.content_hash,
            )
            .order_by(KnowledgeDocument.source_version.desc())
            .limit(1)
        )

        ingested_at = now or datetime.now(UTC)

        if existing is not None:
            self._mark_source_ready(source, ingested_at)
            await self._session.flush()
            return KnowledgePersistenceResult(
                status="unchanged",
                source_id=source.id,
                document_id=existing.id,
                source_version=existing.source_version,
                created_chunks=0,
                created_embeddings=0,
            )

        source_version = source.latest_version + 1
        document = self._build_document(
            source=source,
            source_version=source_version,
            embedded=embedded,
        )
        self._session.add(document)
        await self._session.flush()

        chunks = [
            KnowledgeChunk(
                document_id=document.id,
                ordinal=draft.ordinal,
                content=draft.content,
                content_hash=draft.content_hash,
                token_count=draft.token_count,
                section_path=draft.section_path,
                search_text=draft.search_text,
                metadata_json={
                    **draft.metadata,
                    "page_numbers": list(draft.page_numbers),
                },
            )
            for draft in embedded.prepared.chunks
        ]
        self._session.add_all(chunks)
        await self._session.flush()

        embeddings = [
            KnowledgeEmbedding(
                chunk_id=chunk.id,
                model_name=embedded.model_name,
                model_version=embedded.model_version,
                dimensions=embedded.dimensions,
                embedding=list(vector),
                content_hash=chunk.content_hash,
            )
            for chunk, vector in zip(
                chunks,
                embedded.vectors,
                strict=True,
            )
        ]
        self._session.add_all(embeddings)

        source.latest_version = source_version
        self._mark_source_ready(source, ingested_at)
        await self._session.flush()

        return KnowledgePersistenceResult(
            status="created",
            source_id=source.id,
            document_id=document.id,
            source_version=source_version,
            created_chunks=len(chunks),
            created_embeddings=len(embeddings),
        )

    async def get_source_by_id(
        self,
        source_id: UUID,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None:
        statement = select(KnowledgeSource).where(KnowledgeSource.id == source_id)

        if lock:
            statement = statement.with_for_update()

        return await self._session.scalar(statement)

    async def list_published_documents(
        self,
        source_id: UUID,
        *,
        exclude_document_id: UUID,
        lock: bool = False,
    ) -> list[KnowledgeDocument]:
        statement = (
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source_id,
                KnowledgeDocument.id != exclude_document_id,
                KnowledgeDocument.review_status == "published",
            )
            .order_by(KnowledgeDocument.source_version.asc())
        )

        if lock:
            statement = statement.with_for_update()

        result = await self._session.scalars(statement)
        return list(result.all())

    async def search_full_text(
        self,
        request: KnowledgeRetrievalRequest,
    ) -> list[KnowledgeRetrievalHit]:
        ts_query = func.websearch_to_tsquery(
            "simple",
            request.query,
        )
        raw_rank = func.ts_rank_cd(
            KnowledgeChunk.search_vector,
            ts_query,
        )
        normalized_score = (raw_rank / (raw_rank + 1.0)).label("score")

        statement = (
            select(
                KnowledgeChunk,
                KnowledgeDocument,
                KnowledgeSource,
                normalized_score,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeDocument.source_id,
            )
            .where(
                KnowledgeSource.is_active.is_(True),
                KnowledgeSource.ingest_status == "ready",
                KnowledgeDocument.review_status == "published",
                KnowledgeDocument.topic == request.topic,
                KnowledgeDocument.locale == request.locale,
                KnowledgeChunk.search_vector.bool_op("@@")(ts_query),
            )
            .order_by(
                raw_rank.desc(),
                KnowledgeChunk.id.asc(),
            )
            .limit(request.candidate_k)
        )

        if request.source_keys:
            statement = statement.where(KnowledgeSource.source_key.in_(request.source_keys))

        result = await self._session.execute(statement)

        return [
            self._build_retrieval_hit(
                chunk=chunk,
                document=document,
                source=source,
                score=float(score),
                match_type="full_text",
            )
            for chunk, document, source, score in result.all()
        ]

    async def search_vector(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query_vector: Sequence[float],
        model_name: str,
        model_version: str,
        dimensions: int,
    ) -> list[KnowledgeRetrievalHit]:
        if len(query_vector) != dimensions:
            raise ValueError("query vector dimension does not match dimensions")

        distance = KnowledgeEmbedding.embedding.cosine_distance(list(query_vector))
        normalized_score = func.greatest(
            0.0,
            func.least(
                1.0,
                1.0 - distance,
            ),
        ).label("score")

        statement = (
            select(
                KnowledgeChunk,
                KnowledgeDocument,
                KnowledgeSource,
                normalized_score,
            )
            .select_from(KnowledgeEmbedding)
            .join(
                KnowledgeChunk,
                KnowledgeChunk.id == KnowledgeEmbedding.chunk_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeDocument.source_id,
            )
            .where(
                KnowledgeEmbedding.model_name == model_name,
                KnowledgeEmbedding.model_version == model_version,
                KnowledgeEmbedding.dimensions == dimensions,
                KnowledgeSource.is_active.is_(True),
                KnowledgeSource.ingest_status == "ready",
                KnowledgeDocument.review_status == "published",
                KnowledgeDocument.topic == request.topic,
                KnowledgeDocument.locale == request.locale,
            )
            .order_by(
                distance.asc(),
                KnowledgeChunk.id.asc(),
            )
            .limit(request.candidate_k)
        )

        if request.source_keys:
            statement = statement.where(KnowledgeSource.source_key.in_(request.source_keys))

        result = await self._session.execute(statement)

        return [
            self._build_retrieval_hit(
                chunk=chunk,
                document=document,
                source=source,
                score=float(score),
                match_type="vector",
            )
            for chunk, document, source, score in result.all()
        ]

    @staticmethod
    def _validate_source_metadata(
        source: KnowledgeSource,
        embedded: EmbeddedKnowledgeDocument,
    ) -> None:
        document = embedded.prepared.document
        if source.topic != document.topic or source.locale != document.locale:
            raise KnowledgeSourceMetadataMismatchError(
                "Knowledge source topic or locale does not match the document"
            )

    @staticmethod
    def _build_document(
        *,
        source: KnowledgeSource,
        source_version: int,
        embedded: EmbeddedKnowledgeDocument,
    ) -> KnowledgeDocument:
        prepared = embedded.prepared
        return KnowledgeDocument(
            source_id=source.id,
            source_version=source_version,
            title=prepared.document.title,
            normalized_content=prepared.normalized_content,
            content_hash=prepared.content_hash,
            topic=prepared.document.topic,
            locale=prepared.document.locale,
            review_status="draft",
            metadata_json={
                **prepared.document.metadata,
                "source_key": prepared.document.source_key,
            },
        )

    @staticmethod
    def _mark_source_ready(
        source: KnowledgeSource,
        ingested_at: datetime,
    ) -> None:
        source.ingest_status = "ready"
        source.last_ingested_at = ingested_at
        source.last_error_code = None
        source.last_error_message = None

    @staticmethod
    def _build_retrieval_hit(
        *,
        chunk: KnowledgeChunk,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        score: float,
        match_type: KnowledgeMatchType,
    ) -> KnowledgeRetrievalHit:
        metadata = dict(chunk.metadata_json)
        page_values = metadata.get("page_numbers", ())
        page_numbers = tuple(page_values) if isinstance(page_values, (list, tuple)) else ()

        return KnowledgeRetrievalHit(
            chunk_id=chunk.id,
            document_id=document.id,
            source_id=source.id,
            source_key=source.source_key,
            source_title=source.title,
            source_uri=source.source_uri,
            source_version=document.source_version,
            topic=document.topic,
            locale=document.locale,
            content=chunk.content,
            section_path=chunk.section_path,
            page_numbers=page_numbers,
            score=max(0.0, min(score, 1.0)),
            match_type=match_type,
            metadata=metadata,
        )
