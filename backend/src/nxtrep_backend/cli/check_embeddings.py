import asyncio

from nxtrep_backend.core.config import get_settings
from nxtrep_backend.providers.embeddings import (
    EmbeddingResponseError,
    build_embedding_gateway,
)
from nxtrep_backend.providers.models import ModelConfigurationError


async def check_embedding_connectivity() -> int:
    try:
        gateway = build_embedding_gateway(get_settings())
        vector = await gateway.embed_query("NxtRep 健身知识检索连通性检查")
    except (EmbeddingResponseError, ModelConfigurationError, ValueError) as exc:
        print(f"Embedding configuration check failed: {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:
        print(f"Embedding connectivity check failed: {type(exc).__name__}")
        return 1

    print("Embedding connectivity check passed.")
    print(f"model: {gateway.model_name}")
    print(f"dimensions: {len(vector)}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(check_embedding_connectivity()))


if __name__ == "__main__":
    main()
