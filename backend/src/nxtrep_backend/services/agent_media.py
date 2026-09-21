import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from nxtrep_backend.providers.storage import ImageStorageProvider
from nxtrep_backend.repositories.media import (
    SqlAlchemyImageAssetRepository,
)
from nxtrep_backend.schemas.media import ImagePurpose


@dataclass(frozen=True, slots=True)
class ResolvedAgentImage:
    asset_id: UUID
    purpose: ImagePurpose
    content_type: str
    data: bytes


class AgentImageAssetNotFoundError(RuntimeError):
    pass


class AgentImageAssetNotReadyError(RuntimeError):
    pass


class AgentImageAssetResolver:
    def __init__(
        self,
        repository: SqlAlchemyImageAssetRepository,
        storage: ImageStorageProvider,
    ) -> None:
        self._repository = repository
        self._storage = storage

    async def resolve(
        self,
        *,
        user_id: UUID,
        asset_ids: Sequence[UUID],
    ) -> list[ResolvedAgentImage]:
        assets = []

        for asset_id in asset_ids:
            asset = await self._repository.get_owned(
                user_id=user_id,
                asset_id=asset_id,
            )

            if asset is None:
                raise AgentImageAssetNotFoundError("Image asset not found")

            if asset.status != "ready":
                raise AgentImageAssetNotReadyError(f"Image asset is not ready: {asset.id}")

            assets.append(asset)

        image_data = await asyncio.gather(
            *(self._storage.download_image(asset.object_key) for asset in assets)
        )

        return [
            ResolvedAgentImage(
                asset_id=asset.id,
                purpose=ImagePurpose(asset.purpose),
                content_type=asset.content_type,
                data=data,
            )
            for asset, data in zip(
                assets,
                image_data,
                strict=True,
            )
        ]
