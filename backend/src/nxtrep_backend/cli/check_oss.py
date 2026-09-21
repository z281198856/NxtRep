import asyncio
from uuid import uuid4

from nxtrep_backend.core.config import StorageConfigurationError, get_settings
from nxtrep_backend.providers.storage import (
    ImageObjectNotFoundError,
    StorageProviderError,
    build_image_storage_provider,
)


def _safe_error_chain(error: BaseException) -> str:
    names: list[str] = []
    current: BaseException | None = error
    while current is not None and len(names) < 6:
        names.append(type(current).__name__)
        unwrap = getattr(current, "unwrap", None)
        unwrapped = unwrap() if callable(unwrap) else None
        current = unwrapped if isinstance(unwrapped, BaseException) else current.__cause__
    return " -> ".join(names)


async def check_oss_connectivity() -> int:
    try:
        settings = get_settings()
        provider = build_image_storage_provider(settings)
        object_key = f"{settings.oss_object_prefix}/connectivity-check/{uuid4()}.jpg"
        await provider.verify_image(object_key)
    except ImageObjectNotFoundError:
        print("OSS connectivity check passed.")
        return 0
    except (StorageConfigurationError, StorageProviderError) as exc:
        print(f"OSS connectivity check failed: {exc} [{_safe_error_chain(exc)}]")
        return 1

    print("OSS connectivity check failed: random object unexpectedly exists.")
    return 1


def main() -> None:
    raise SystemExit(asyncio.run(check_oss_connectivity()))


if __name__ == "__main__":
    main()
