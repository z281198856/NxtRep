import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nxtrep_backend.db.models import ImageAsset, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_image_asset_persists_with_database_constraints() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            user = User(
                username=f"media-owner-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add(user)
            await session.flush()

            asset = ImageAsset(
                user_id=user.id,
                purpose="nutrition_entry",
                object_key=f"images/{user.id}/{uuid4()}.jpg",
                content_type="image/jpeg",
                content_length=2048,
                upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(asset)
            await session.flush()

            persisted = await session.scalar(
                select(ImageAsset).where(
                    ImageAsset.id == asset.id,
                    ImageAsset.user_id == user.id,
                )
            )

            assert persisted is not None
            assert persisted.status == "pending_upload"
            assert persisted.object_key == asset.object_key

            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        ImageAsset(
                            user_id=user.id,
                            purpose="chat_attachment",
                            object_key=f"images/{user.id}/{uuid4()}.png",
                            content_type="image/png",
                            content_length=0,
                            upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                        )
                    )
                    await session.flush()
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_image_repository_enforces_owner_and_soft_delete_visibility() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()

        try:
            owner = User(
                username=f"media-owner-{uuid4().hex}",
                password_setup_required=False,
            )
            other_user = User(
                username=f"media-other-{uuid4().hex}",
                password_setup_required=False,
            )
            session.add_all([owner, other_user])
            await session.flush()

            repository = SqlAlchemyImageAssetRepository(session)
            asset = await repository.add(
                ImageAsset(
                    user_id=owner.id,
                    purpose="body_progress",
                    object_key=f"images/{owner.id}/{uuid4()}.webp",
                    content_type="image/webp",
                    content_length=4096,
                    upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )

            assert (
                await repository.get_owned(
                    user_id=owner.id,
                    asset_id=asset.id,
                )
                is asset
            )
            assert (
                await repository.get_owned(
                    user_id=other_user.id,
                    asset_id=asset.id,
                )
                is None
            )

            asset.status = "deleted"
            asset.deleted_at = datetime.now(UTC)
            await repository.save(asset)

            assert (
                await repository.get_owned(
                    user_id=owner.id,
                    asset_id=asset.id,
                )
                is None
            )
            assert (
                await repository.get_owned(
                    user_id=owner.id,
                    asset_id=asset.id,
                    include_deleted=True,
                )
                is asset
            )
        finally:
            await transaction.rollback()
