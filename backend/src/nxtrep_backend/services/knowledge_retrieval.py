from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.core.config import Settings
from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)
from nxtrep_backend.providers.embeddings import (
    EmbeddingGateway,
    build_embedding_gateway,
)
from nxtrep_backend.repositories.knowledge import (
    SqlAlchemyKnowledgeRepository,
)

_RRF_K = 60
_FALLBACK_LOCALE = "en"


class KnowledgeRetrievalRepository(Protocol):
    async def search_full_text(
        self,
        request: KnowledgeRetrievalRequest,
    ) -> Sequence[KnowledgeRetrievalHit]: ...

    async def search_vector(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query_vector: Sequence[float],
        model_name: str,
        model_version: str,
        dimensions: int,
    ) -> Sequence[KnowledgeRetrievalHit]: ...


class KnowledgeRetrievalMerger:
    """使用倒数排名融合合并全文和向量检索结果。"""

    def merge(
        self,
        *,
        full_text_hits: Sequence[KnowledgeRetrievalHit],
        vector_hits: Sequence[KnowledgeRetrievalHit],
        top_k: int,
    ) -> tuple[KnowledgeRetrievalHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")

        hits_by_id: dict[UUID, KnowledgeRetrievalHit] = {}
        scores_by_id: dict[UUID, float] = {}
        channels_by_id: dict[UUID, set[str]] = {}

        self._add_channel(
            hits=full_text_hits,
            channel="full_text",
            hits_by_id=hits_by_id,
            scores_by_id=scores_by_id,
            channels_by_id=channels_by_id,
        )
        self._add_channel(
            hits=vector_hits,
            channel="vector",
            hits_by_id=hits_by_id,
            scores_by_id=scores_by_id,
            channels_by_id=channels_by_id,
        )

        maximum_score = 2 / (_RRF_K + 1)
        merged: list[KnowledgeRetrievalHit] = []

        for chunk_id, hit in hits_by_id.items():
            channels = channels_by_id[chunk_id]
            match_type = "hybrid" if len(channels) == 2 else next(iter(channels))
            normalized_score = min(
                scores_by_id[chunk_id] / maximum_score,
                1.0,
            )

            merged.append(
                replace(
                    hit,
                    score=normalized_score,
                    match_type=match_type,
                )
            )

        merged.sort(
            key=lambda hit: (
                -hit.score,
                hit.source_key,
                hit.source_version,
                str(hit.chunk_id),
            )
        )
        return tuple(merged[:top_k])

    @staticmethod
    def _add_channel(
        *,
        hits: Sequence[KnowledgeRetrievalHit],
        channel: str,
        hits_by_id: dict[UUID, KnowledgeRetrievalHit],
        scores_by_id: dict[UUID, float],
        channels_by_id: dict[UUID, set[str]],
    ) -> None:
        for rank, hit in enumerate(hits, start=1):
            chunk_id = hit.chunk_id

            hits_by_id.setdefault(chunk_id, hit)
            scores_by_id[chunk_id] = scores_by_id.get(chunk_id, 0.0) + 1 / (_RRF_K + rank)
            channels_by_id.setdefault(chunk_id, set()).add(channel)


class KnowledgeRetrievalService:
    """协调查询向量生成、两路检索和结果融合。"""

    def __init__(
        self,
        *,
        repository: KnowledgeRetrievalRepository,
        embeddings: EmbeddingGateway,
        embedding_model_version: str,
        minimum_vector_score: float = 0.5,
        merger: KnowledgeRetrievalMerger | None = None,
    ) -> None:
        normalized_version = embedding_model_version.strip()
        if not normalized_version:
            raise ValueError("embedding model version must not be blank")

        self._repository = repository
        self._embeddings = embeddings
        self._embedding_model_version = normalized_version
        if not 0 <= minimum_vector_score <= 1:
            raise ValueError("minimum vector score must be between 0 and 1")
        self._minimum_vector_score = minimum_vector_score
        self._merger = merger or KnowledgeRetrievalMerger()

    async def retrieve(
        self,
        request: KnowledgeRetrievalRequest,
    ) -> tuple[KnowledgeRetrievalHit, ...]:
        query_vector = tuple(await self._embeddings.embed_query(request.query))

        if len(query_vector) != self._embeddings.dimensions:
            raise ValueError("query vector dimension does not match embedding configuration")

        hits = await self._retrieve_for_locale(
            request=request,
            query_vector=query_vector,
        )
        if hits or request.locale.casefold() == _FALLBACK_LOCALE:
            return hits

        return await self._retrieve_for_locale(
            request=replace(request, locale=_FALLBACK_LOCALE),
            query_vector=query_vector,
        )

    async def _retrieve_for_locale(
        self,
        *,
        request: KnowledgeRetrievalRequest,
        query_vector: Sequence[float],
    ) -> tuple[KnowledgeRetrievalHit, ...]:
        full_text_hits = await self._repository.search_full_text(request)
        raw_vector_hits = await self._repository.search_vector(
            request,
            query_vector=query_vector,
            model_name=self._embeddings.model_name,
            model_version=self._embedding_model_version,
            dimensions=self._embeddings.dimensions,
        )
        vector_hits = tuple(
            hit for hit in raw_vector_hits if hit.score >= self._minimum_vector_score
        )

        return self._merger.merge(
            full_text_hits=full_text_hits,
            vector_hits=vector_hits,
            top_k=request.top_k,
        )


def build_knowledge_retrieval_service(
    *,
    session: AsyncSession,
    settings: Settings,
) -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService(
        repository=SqlAlchemyKnowledgeRepository(session),
        embeddings=build_embedding_gateway(settings),
        embedding_model_version=settings.embedding_model_version,
        minimum_vector_score=settings.rag_min_vector_score,
    )
