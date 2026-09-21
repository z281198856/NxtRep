from math import isfinite
from typing import Protocol

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.models import ModelConfigurationError


class EmbeddingResponseError(RuntimeError):
    """Raised when an embedding provider returns unsafe or incompatible vectors."""


class EmbeddingGateway(Protocol):
    model_name: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class GlmEmbeddingGateway:
    """Generate validated GLM embeddings without exposing provider details to RAG services."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Embeddings | None = None,
    ) -> None:
        if settings.glm_api_key is None and client is None:
            raise ModelConfigurationError("NXTREP_GLM_API_KEY is not configured")
        self.model_name = settings.glm_embedding_model
        self.dimensions = settings.embedding_dimensions
        self._batch_size = settings.embedding_batch_size
        if client is not None:
            self._client = client
        else:
            options = {
                "model": self.model_name,
                "dimensions": self.dimensions,
                "api_key": settings.glm_api_key.get_secret_value(),
                "base_url": settings.glm_base_url,
                "timeout": settings.embedding_timeout_seconds,
                "max_retries": settings.embedding_max_retries,
                "check_embedding_ctx_length": False,
            }
            if settings.llm_proxy_url is not None:
                options["openai_proxy"] = str(settings.llm_proxy_url)
            self._client = OpenAIEmbeddings(**options)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        normalized = [self._normalize_text(text) for text in texts]
        vectors: list[list[float]] = []
        for offset in range(0, len(normalized), self._batch_size):
            batch = normalized[offset : offset + self._batch_size]
            response = await self._client.aembed_documents(batch)
            vectors.extend(self._validate_vectors(response, expected_count=len(batch)))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        response = await self._client.aembed_query(self._normalize_text(text))
        return self._validate_vectors([response], expected_count=1)[0]

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Embedding input must not be blank")
        return normalized

    def _validate_vectors(
        self,
        vectors: list[list[float]],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise EmbeddingResponseError("Embedding provider returned an unexpected vector count")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingResponseError("Embedding provider returned an unexpected dimension")
            if not all(isfinite(value) for value in vector):
                raise EmbeddingResponseError("Embedding provider returned a non-finite value")
        return vectors


def build_embedding_gateway(settings: Settings) -> EmbeddingGateway:
    if settings.embedding_provider == "glm":
        return GlmEmbeddingGateway(settings)
    raise ModelConfigurationError("Unsupported embedding provider")
