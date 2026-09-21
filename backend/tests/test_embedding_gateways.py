from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from nxtrep_backend.core.config import Settings
from nxtrep_backend.providers.embeddings import (
    EmbeddingResponseError,
    GlmEmbeddingGateway,
    build_embedding_gateway,
)
from nxtrep_backend.providers.models import ModelConfigurationError

TEST_DIMENSIONS = 256


def make_settings(**values) -> Settings:
    return Settings(
        _env_file=None,
        glm_api_key=SecretStr("test-glm-key"),
        embedding_dimensions=TEST_DIMENSIONS,
        **values,
    )


@pytest.mark.asyncio
async def test_embedding_gateway_normalizes_and_batches_documents() -> None:
    client = AsyncMock()
    client.aembed_documents.side_effect = [
        [[1.0] * TEST_DIMENSIONS, [0.5] * TEST_DIMENSIONS],
        [[0.25] * TEST_DIMENSIONS],
    ]
    gateway = GlmEmbeddingGateway(
        make_settings(embedding_batch_size=2),
        client=client,
    )

    vectors = await gateway.embed_documents([" 第一段 ", "第二段", "第三段"])

    assert len(vectors) == 3
    assert client.aembed_documents.await_args_list[0].args[0] == ["第一段", "第二段"]
    assert client.aembed_documents.await_args_list[1].args[0] == ["第三段"]


@pytest.mark.asyncio
async def test_embedding_gateway_validates_query_dimension() -> None:
    client = AsyncMock()
    client.aembed_query.return_value = [0.1, 0.2]
    gateway = GlmEmbeddingGateway(make_settings(), client=client)

    with pytest.raises(EmbeddingResponseError, match="dimension"):
        await gateway.embed_query("如何做深蹲")


@pytest.mark.asyncio
async def test_embedding_gateway_rejects_non_finite_values() -> None:
    client = AsyncMock()
    client.aembed_query.return_value = [0.1] * (TEST_DIMENSIONS - 1) + [float("nan")]
    gateway = GlmEmbeddingGateway(make_settings(), client=client)

    with pytest.raises(EmbeddingResponseError, match="non-finite"):
        await gateway.embed_query("深蹲安全提示")


@pytest.mark.asyncio
async def test_embedding_gateway_rejects_blank_input_without_calling_provider() -> None:
    client = AsyncMock()
    gateway = GlmEmbeddingGateway(make_settings(), client=client)

    with pytest.raises(ValueError, match="blank"):
        await gateway.embed_query("   ")

    client.aembed_query.assert_not_awaited()


def test_embedding_gateway_requires_glm_key() -> None:
    settings = Settings(_env_file=None, glm_api_key=None)

    with pytest.raises(ModelConfigurationError, match="NXTREP_GLM_API_KEY"):
        build_embedding_gateway(settings)


def test_rag_top_k_cannot_exceed_candidate_k() -> None:
    with pytest.raises(ValidationError, match="rag_top_k"):
        Settings(_env_file=None, rag_candidate_k=5, rag_top_k=6)


def test_embedding_model_version_defaults_to_v1() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_model_version == "v1"


def test_embedding_gateway_uses_explicit_proxy_configuration() -> None:
    gateway = GlmEmbeddingGateway(
        make_settings(llm_proxy_url="http://127.0.0.1:10808")
    )

    assert gateway._client.openai_proxy == "http://127.0.0.1:10808/"


def test_embedding_model_version_accepts_environment_and_trims_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NXTREP_EMBEDDING_MODEL_VERSION",
        " release-2026-09 ",
    )

    settings = Settings(_env_file=None)

    assert settings.embedding_model_version == "release-2026-09"


@pytest.mark.parametrize("value", [" ", "x" * 81])
def test_embedding_model_version_rejects_invalid_value(value: str) -> None:
    with pytest.raises(ValidationError, match="embedding_model_version"):
        Settings(_env_file=None, embedding_model_version=value)
