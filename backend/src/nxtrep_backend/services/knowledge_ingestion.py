from collections.abc import Iterable
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.core.config import Settings
from nxtrep_backend.knowledge.chunker import KnowledgeChunker
from nxtrep_backend.knowledge.loaders.base import KnowledgeDocumentLoader
from nxtrep_backend.knowledge.loaders.html import HtmlDocumentLoader
from nxtrep_backend.knowledge.loaders.pdf import PdfDocumentLoader
from nxtrep_backend.knowledge.normalizer import KnowledgeTextNormalizer
from nxtrep_backend.knowledge.schemas import (
    EmbeddedKnowledgeDocument,
    KnowledgeLoadRequest,
    PreparedKnowledgeDocument,
)
from nxtrep_backend.providers.embeddings import (
    EmbeddingGateway,
    build_embedding_gateway,
)
from nxtrep_backend.repositories.knowledge import (
    KnowledgePersistenceResult,
    SqlAlchemyKnowledgeRepository,
)


class UnsupportedKnowledgeContentTypeError(ValueError):
    """摄取服务没有配置能够处理该内容类型的 Loader。"""


class KnowledgeDocumentPreparer:
    """协调知识文件的确定性加载、清洗和切块阶段。"""

    def __init__(
        self,
        *,
        loaders: Iterable[KnowledgeDocumentLoader],
        normalizer: KnowledgeTextNormalizer,
        chunker: KnowledgeChunker,
    ) -> None:
        self._loaders = self._index_loaders(loaders)
        self._normalizer = normalizer
        self._chunker = chunker

    def prepare(
        self,
        request: KnowledgeLoadRequest,
    ) -> PreparedKnowledgeDocument:
        loader = self._loaders.get(request.content_type)

        if loader is None:
            raise UnsupportedKnowledgeContentTypeError(
                f"Unsupported knowledge content type: {request.content_type}"
            )

        loaded_document = loader.load(request)
        normalized_document = self._normalizer.normalize(loaded_document)
        chunks = self._chunker.chunk(normalized_document)
        normalized_content = "\n\n".join(block.text for block in normalized_document.blocks)
        content_hash = sha256(normalized_content.encode("utf-8")).hexdigest()

        return PreparedKnowledgeDocument(
            document=normalized_document,
            normalized_content=normalized_content,
            content_hash=content_hash,
            chunks=chunks,
        )

    @staticmethod
    def _index_loaders(
        loaders: Iterable[KnowledgeDocumentLoader],
    ) -> dict[str, KnowledgeDocumentLoader]:
        indexed: dict[str, KnowledgeDocumentLoader] = {}

        for loader in loaders:
            for content_type in loader.supported_content_types:
                if content_type in indexed:
                    raise ValueError(
                        f"Multiple knowledge loaders configured for content type: {content_type}"
                    )
                indexed[content_type] = loader

        if not indexed:
            raise ValueError("At least one knowledge loader must be configured")

        return indexed


class KnowledgeDocumentVectorizer:
    """将准备好的知识切片批量转换成经过校验的向量。"""

    def __init__(
        self,
        gateway: EmbeddingGateway,
        *,
        model_version: str,
    ) -> None:
        normalized_version = model_version.strip()
        if not normalized_version:
            raise ValueError("model_version must not be blank")

        self._gateway = gateway
        self._model_version = normalized_version

    async def vectorize(
        self,
        prepared: PreparedKnowledgeDocument,
    ) -> EmbeddedKnowledgeDocument:
        vectors = await self._gateway.embed_documents([chunk.content for chunk in prepared.chunks])

        return EmbeddedKnowledgeDocument(
            prepared=prepared,
            model_name=self._gateway.model_name,
            model_version=self._model_version,
            dimensions=self._gateway.dimensions,
            vectors=tuple(tuple(vector) for vector in vectors),
        )


class KnowledgePersistenceRepository(Protocol):
    async def persist_embedded_document(
        self,
        *,
        source_id: UUID,
        embedded: EmbeddedKnowledgeDocument,
    ) -> KnowledgePersistenceResult: ...


class KnowledgeIngestionService:
    """编排准备、向量化和原子持久化三个摄取阶段。"""

    def __init__(
        self,
        *,
        preparer: KnowledgeDocumentPreparer,
        vectorizer: KnowledgeDocumentVectorizer,
        repository: KnowledgePersistenceRepository,
    ) -> None:
        self._preparer = preparer
        self._vectorizer = vectorizer
        self._repository = repository

    async def ingest(
        self,
        *,
        source_id: UUID,
        request: KnowledgeLoadRequest,
    ) -> KnowledgePersistenceResult:
        prepared = self._preparer.prepare(request)
        embedded = await self._vectorizer.vectorize(prepared)
        return await self._repository.persist_embedded_document(
            source_id=source_id,
            embedded=embedded,
        )


def build_knowledge_document_preparer() -> KnowledgeDocumentPreparer:
    """构建支持项目当前 PDF 和 HTML 来源的默认准备器。"""
    return KnowledgeDocumentPreparer(
        loaders=(
            PdfDocumentLoader(),
            HtmlDocumentLoader(),
        ),
        normalizer=KnowledgeTextNormalizer(),
        chunker=KnowledgeChunker(),
    )


def build_knowledge_ingestion_service(
    *,
    session: AsyncSession,
    settings: Settings,
) -> KnowledgeIngestionService:
    """把运行时依赖组装成完整的知识摄取服务。"""
    gateway = build_embedding_gateway(settings)
    vectorizer = KnowledgeDocumentVectorizer(
        gateway,
        model_version=settings.embedding_model_version,
    )
    repository = SqlAlchemyKnowledgeRepository(session)

    return KnowledgeIngestionService(
        preparer=build_knowledge_document_preparer(),
        vectorizer=vectorizer,
        repository=repository,
    )
