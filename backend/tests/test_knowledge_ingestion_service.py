from hashlib import sha256
from pathlib import Path
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

import nxtrep_backend.services.knowledge_ingestion as ingestion_module
from nxtrep_backend.core.config import Settings
from nxtrep_backend.knowledge.chunker import ChunkingConfig, KnowledgeChunker
from nxtrep_backend.knowledge.loaders.html import HtmlDocumentLoader
from nxtrep_backend.knowledge.normalizer import KnowledgeTextNormalizer
from nxtrep_backend.knowledge.schemas import (
    EmbeddedKnowledgeDocument,
    KnowledgeLoadRequest,
)
from nxtrep_backend.repositories.knowledge import (
    KnowledgePersistenceResult,
    SqlAlchemyKnowledgeRepository,
)
from nxtrep_backend.services.knowledge_ingestion import (
    KnowledgeDocumentPreparer,
    KnowledgeDocumentVectorizer,
    KnowledgeIngestionService,
    UnsupportedKnowledgeContentTypeError,
    build_knowledge_ingestion_service,
)


class CharacterTokenCounter:
    @property
    def name(self) -> str:
        return "characters:v1"

    def count(self, text: str) -> int:
        return len(text)


class FakeEmbeddingGateway:
    model_name = "embedding-test"
    dimensions = 3

    def __init__(
        self,
        vectors: list[list[float]] | None = None,
    ) -> None:
        self.vectors = vectors
        self.received_texts: list[str] = []

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        self.received_texts = texts
        return self.vectors if self.vectors is not None else [
            [float(index), 0.5, 1.0]
            for index, _ in enumerate(texts)
        ]

    async def embed_query(self, text: str) -> list[float]:
        raise AssertionError("The ingestion vectorizer must not embed a query")


class FakeKnowledgeRepository:
    def __init__(self) -> None:
        self.received_source_id: UUID | None = None
        self.received_document: EmbeddedKnowledgeDocument | None = None

    async def persist_embedded_document(
        self,
        *,
        source_id: UUID,
        embedded: EmbeddedKnowledgeDocument,
    ) -> KnowledgePersistenceResult:
        self.received_source_id = source_id
        self.received_document = embedded
        return KnowledgePersistenceResult(
            status="created",
            source_id=source_id,
            document_id=uuid4(),
            source_version=1,
            created_chunks=len(embedded.prepared.chunks),
            created_embeddings=len(embedded.vectors),
        )


def build_preparer() -> KnowledgeDocumentPreparer:
    return KnowledgeDocumentPreparer(
        loaders=(HtmlDocumentLoader(),),
        normalizer=KnowledgeTextNormalizer(),
        chunker=KnowledgeChunker(
            token_counter=CharacterTokenCounter(),
            config=ChunkingConfig(
                target_tokens=40,
                max_tokens=60,
                overlap_tokens=0,
            ),
        ),
    )


def make_request(path: Path, *, content_type: str = "text/html") -> KnowledgeLoadRequest:
    return KnowledgeLoadRequest(
        path=path,
        source_key="national-fitness-guide",
        title="全民健身指南",
        topic="training",
        locale="zh-CN",
        content_type=content_type,
    )


def test_prepare_runs_load_normalize_and_chunk_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        """
        <html><body><article>
          <h1>一、训练原则</h1>
          <p>动作应当循序渐进。</p>
          <h1>二、安全原则</h1>
          <p>出现明显疼痛时应停止训练。</p>
        </article></body></html>
        """,
        encoding="utf-8",
    )

    prepared = build_preparer().prepare(make_request(source))

    assert prepared.document.source_key == "national-fitness-guide"
    assert prepared.document.metadata["normalization_version"] == "v1"
    assert prepared.normalized_content == (
        "一、训练原则\n\n动作应当循序渐进。\n\n"
        "二、安全原则\n\n出现明显疼痛时应停止训练。"
    )
    assert prepared.content_hash == sha256(
        prepared.normalized_content.encode("utf-8")
    ).hexdigest()
    assert len(prepared.chunks) == 2
    assert [chunk.section_path for chunk in prepared.chunks] == [
        "一、训练原则",
        "二、安全原则",
    ]


def test_prepare_rejects_unconfigured_content_type(tmp_path: Path) -> None:
    source = tmp_path / "guide.txt"
    source.write_text("training guidance", encoding="utf-8")

    with pytest.raises(
        UnsupportedKnowledgeContentTypeError,
        match="text/plain",
    ):
        build_preparer().prepare(
            make_request(source, content_type="text/plain")
        )


def test_service_rejects_duplicate_loader_registration() -> None:
    with pytest.raises(ValueError, match="Multiple knowledge loaders"):
        KnowledgeDocumentPreparer(
            loaders=(HtmlDocumentLoader(), HtmlDocumentLoader()),
            normalizer=KnowledgeTextNormalizer(),
            chunker=KnowledgeChunker(
                token_counter=CharacterTokenCounter(),
            ),
        )


def test_service_requires_at_least_one_loader() -> None:
    with pytest.raises(ValueError, match="At least one knowledge loader"):
        KnowledgeDocumentPreparer(
            loaders=(),
            normalizer=KnowledgeTextNormalizer(),
            chunker=KnowledgeChunker(
                token_counter=CharacterTokenCounter(),
            ),
        )


@pytest.mark.asyncio
async def test_vectorizer_embeds_every_chunk_in_order(tmp_path: Path) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        """
        <html><body><article>
          <h1>第一章</h1><p>动作稳定</p>
          <h1>第二章</h1><p>逐步加量</p>
        </article></body></html>
        """,
        encoding="utf-8",
    )
    prepared = build_preparer().prepare(make_request(source))
    gateway = FakeEmbeddingGateway()

    embedded = await KnowledgeDocumentVectorizer(
        gateway,
        model_version="test-v1",
    ).vectorize(prepared)

    assert gateway.received_texts == [
        chunk.content for chunk in prepared.chunks
    ]
    assert embedded.prepared is prepared
    assert embedded.model_name == "embedding-test"
    assert embedded.model_version == "test-v1"
    assert embedded.dimensions == 3
    assert len(embedded.vectors) == len(prepared.chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vectors", "message"),
    [
        ([], "one vector per chunk"),
        ([[0.0, 1.0]], "dimensions do not match"),
        ([[0.0, float("nan"), 1.0]], "finite values"),
    ],
)
async def test_vectorizer_rejects_invalid_gateway_results(
    tmp_path: Path,
    vectors: list[list[float]],
    message: str,
) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        "<html><body><article><p>动作稳定</p></article></body></html>",
        encoding="utf-8",
    )
    prepared = build_preparer().prepare(make_request(source))

    with pytest.raises(ValueError, match=message):
        await KnowledgeDocumentVectorizer(
            FakeEmbeddingGateway(vectors),
            model_version="test-v1",
        ).vectorize(prepared)


def test_vectorizer_requires_model_version() -> None:
    with pytest.raises(ValueError, match="model_version"):
        KnowledgeDocumentVectorizer(
            FakeEmbeddingGateway(),
            model_version=" ",
        )


@pytest.mark.asyncio
async def test_ingestion_service_runs_prepare_vectorize_and_persist(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        "<html><body><article><p>动作稳定</p></article></body></html>",
        encoding="utf-8",
    )
    source_id = uuid4()
    gateway = FakeEmbeddingGateway()
    repository = FakeKnowledgeRepository()
    service = KnowledgeIngestionService(
        preparer=build_preparer(),
        vectorizer=KnowledgeDocumentVectorizer(
            gateway,
            model_version="test-v1",
        ),
        repository=repository,
    )

    result = await service.ingest(
        source_id=source_id,
        request=make_request(source),
    )

    assert result.status == "created"
    assert result.source_id == source_id
    assert result.created_chunks == 1
    assert result.created_embeddings == 1
    assert repository.received_source_id == source_id
    assert repository.received_document is not None
    assert repository.received_document.model_name == "embedding-test"
    assert gateway.received_texts == ["动作稳定"]


@pytest.mark.asyncio
async def test_ingestion_service_does_not_persist_when_vectorization_fails(
    tmp_path: Path,
) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        "<html><body><article><p>动作稳定</p></article></body></html>",
        encoding="utf-8",
    )
    repository = FakeKnowledgeRepository()
    service = KnowledgeIngestionService(
        preparer=build_preparer(),
        vectorizer=KnowledgeDocumentVectorizer(
            FakeEmbeddingGateway(vectors=[]),
            model_version="test-v1",
        ),
        repository=repository,
    )

    with pytest.raises(ValueError, match="one vector per chunk"):
        await service.ingest(
            source_id=uuid4(),
            request=make_request(source),
        )

    assert repository.received_source_id is None
    assert repository.received_document is None


def test_factory_wires_settings_gateway_session_and_model_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeEmbeddingGateway()
    gateway_builder = Mock(return_value=gateway)
    monkeypatch.setattr(
        ingestion_module,
        "build_embedding_gateway",
        gateway_builder,
    )
    settings = Settings(
        _env_file=None,
        glm_api_key=SecretStr("test-key"),
        embedding_model_version="release-v2",
    )
    session = cast(AsyncSession, object())

    service = build_knowledge_ingestion_service(
        session=session,
        settings=settings,
    )

    gateway_builder.assert_called_once_with(settings)
    assert isinstance(service, KnowledgeIngestionService)
    assert isinstance(service._preparer, KnowledgeDocumentPreparer)
    assert isinstance(service._vectorizer, KnowledgeDocumentVectorizer)
    assert service._vectorizer._gateway is gateway
    assert service._vectorizer._model_version == "release-v2"
    assert isinstance(service._repository, SqlAlchemyKnowledgeRepository)
    assert service._repository._session is session
