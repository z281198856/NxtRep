from collections.abc import Sequence
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import nxtrep_backend.services.knowledge_retrieval as retrieval_module
from nxtrep_backend.core.config import Settings
from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.services.knowledge_retrieval import (
    KnowledgeRetrievalService,
    build_knowledge_retrieval_service,
)


class FakeEmbeddingGateway:
    model_name = "embedding-3"
    dimensions = 3

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [0.1, 0.2, 0.3]
        self.queries: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.vector


class FakeKnowledgeRetrievalRepository:
    def __init__(
        self,
        *,
        full_text_hits: Sequence[KnowledgeRetrievalHit] = (),
        vector_hits: Sequence[KnowledgeRetrievalHit] = (),
    ) -> None:
        self.full_text_hits = full_text_hits
        self.vector_hits = vector_hits
        self.full_text_requests: list[KnowledgeRetrievalRequest] = []
        self.vector_calls: list[
            tuple[
                KnowledgeRetrievalRequest,
                tuple[float, ...],
                str,
                str,
                int,
            ]
        ] = []

    async def search_full_text(
        self,
        request: KnowledgeRetrievalRequest,
    ) -> Sequence[KnowledgeRetrievalHit]:
        self.full_text_requests.append(request)
        return self.full_text_hits

    async def search_vector(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query_vector: Sequence[float],
        model_name: str,
        model_version: str,
        dimensions: int,
    ) -> Sequence[KnowledgeRetrievalHit]:
        self.vector_calls.append(
            (
                request,
                tuple(query_vector),
                model_name,
                model_version,
                dimensions,
            )
        )
        return self.vector_hits


def build_hit(
    chunk_id: UUID,
    *,
    match_type: str,
    source_key: str,
    locale: str = "zh-CN",
    score: float = 0.5,
) -> KnowledgeRetrievalHit:
    return KnowledgeRetrievalHit(
        chunk_id=chunk_id,
        document_id=uuid4(),
        source_id=uuid4(),
        source_key=source_key,
        source_title=f"Source {source_key}",
        source_uri=f"https://example.com/{source_key}",
        source_version=1,
        topic="exercise",
        locale=locale,
        content=f"Content for {source_key}",
        section_path="深蹲",
        page_numbers=(1,),
        score=score,
        match_type=match_type,
    )


def build_request() -> KnowledgeRetrievalRequest:
    return KnowledgeRetrievalRequest(
        query="如何安全地进行深蹲？",
        topic="exercise",
        locale="zh-CN",
        candidate_k=20,
        top_k=2,
        source_keys=("official-guide",),
    )


@pytest.mark.asyncio
async def test_retrieve_embeds_query_runs_both_channels_and_merges() -> None:
    shared_id = uuid4()
    text_only_id = uuid4()
    vector_only_id = uuid4()
    repository = FakeKnowledgeRetrievalRepository(
        full_text_hits=(
            build_hit(
                text_only_id,
                match_type="full_text",
                source_key="text-only",
            ),
            build_hit(
                shared_id,
                match_type="full_text",
                source_key="shared",
            ),
        ),
        vector_hits=(
            build_hit(
                shared_id,
                match_type="vector",
                source_key="shared",
            ),
            build_hit(
                vector_only_id,
                match_type="vector",
                source_key="vector-only",
            ),
        ),
    )
    embeddings = FakeEmbeddingGateway()
    request = build_request()
    service = KnowledgeRetrievalService(
        repository=repository,
        embeddings=embeddings,
        embedding_model_version="v1",
    )

    result = await service.retrieve(request)

    assert embeddings.queries == [request.query]
    assert repository.full_text_requests == [request]
    assert repository.vector_calls == [
        (
            request,
            (0.1, 0.2, 0.3),
            "embedding-3",
            "v1",
            3,
        )
    ]
    assert [hit.chunk_id for hit in result] == [shared_id, text_only_id]
    assert result[0].match_type == "hybrid"


@pytest.mark.asyncio
async def test_retrieve_returns_empty_tuple_when_database_has_no_hits() -> None:
    repository = FakeKnowledgeRetrievalRepository()
    service = KnowledgeRetrievalService(
        repository=repository,
        embeddings=FakeEmbeddingGateway(),
        embedding_model_version="v1",
    )

    result = await service.retrieve(build_request())

    assert result == ()


@pytest.mark.asyncio
async def test_retrieve_rejects_vector_hits_below_evidence_threshold() -> None:
    weak_hit = build_hit(
        uuid4(),
        match_type="vector",
        source_key="weak-match",
        score=0.49,
    )
    repository = FakeKnowledgeRetrievalRepository(vector_hits=(weak_hit,))
    service = KnowledgeRetrievalService(
        repository=repository,
        embeddings=FakeEmbeddingGateway(),
        embedding_model_version="v1",
        minimum_vector_score=0.5,
    )

    result = await service.retrieve(build_request())

    assert result == ()


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_english_without_embedding_query_twice() -> None:
    english_hit = build_hit(
        uuid4(),
        match_type="vector",
        source_key="english-guide",
        locale="en",
    )

    class LocaleAwareRepository(FakeKnowledgeRetrievalRepository):
        async def search_vector(
            self,
            request: KnowledgeRetrievalRequest,
            *,
            query_vector: Sequence[float],
            model_name: str,
            model_version: str,
            dimensions: int,
        ) -> Sequence[KnowledgeRetrievalHit]:
            await super().search_vector(
                request,
                query_vector=query_vector,
                model_name=model_name,
                model_version=model_version,
                dimensions=dimensions,
            )
            return (english_hit,) if request.locale == "en" else ()

    repository = LocaleAwareRepository()
    embeddings = FakeEmbeddingGateway()
    service = KnowledgeRetrievalService(
        repository=repository,
        embeddings=embeddings,
        embedding_model_version="v1",
    )

    result = await service.retrieve(build_request())

    assert result == (english_hit,)
    assert embeddings.queries == ["如何安全地进行深蹲？"]
    assert [request.locale for request in repository.full_text_requests] == [
        "zh-CN",
        "en",
    ]
    assert [call[0].locale for call in repository.vector_calls] == [
        "zh-CN",
        "en",
    ]


def test_retrieval_service_rejects_blank_model_version() -> None:
    with pytest.raises(ValueError, match="model version must not be blank"):
        KnowledgeRetrievalService(
            repository=FakeKnowledgeRetrievalRepository(),
            embeddings=FakeEmbeddingGateway(),
            embedding_model_version=" ",
        )


@pytest.mark.asyncio
async def test_retrieve_rejects_unexpected_query_vector_dimension() -> None:
    service = KnowledgeRetrievalService(
        repository=FakeKnowledgeRetrievalRepository(),
        embeddings=FakeEmbeddingGateway(vector=[0.1, 0.2]),
        embedding_model_version="v1",
    )

    with pytest.raises(ValueError, match="query vector dimension"):
        await service.retrieve(build_request())


def test_build_retrieval_service_wires_repository_embedding_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=AsyncSession)
    settings = Settings(
        _env_file=None,
        embedding_model_version="release-2026-09",
    )
    embeddings = FakeEmbeddingGateway()
    received_settings: list[Settings] = []

    def build_embeddings(received: Settings) -> FakeEmbeddingGateway:
        received_settings.append(received)
        return embeddings

    monkeypatch.setattr(
        retrieval_module,
        "build_embedding_gateway",
        build_embeddings,
    )

    service = build_knowledge_retrieval_service(
        session=session,
        settings=settings,
    )

    assert isinstance(service, KnowledgeRetrievalService)
    assert isinstance(service._repository, SqlAlchemyKnowledgeRepository)
    assert service._repository._session is session
    assert service._embeddings is embeddings
    assert service._embedding_model_version == "release-2026-09"
    assert service._minimum_vector_score == 0.5
    assert received_settings == [settings]
