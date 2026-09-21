from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.repositories.media import SqlAlchemyImageAssetRepository


def compile_statement(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def make_asset() -> ImageAsset:
    user_id = uuid4()
    return ImageAsset(
        id=uuid4(),
        user_id=user_id,
        purpose="chat_attachment",
        object_key=f"images/{user_id}/{uuid4()}.jpg",
        content_type="image/jpeg",
        content_length=2048,
        upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )


@pytest.mark.asyncio
async def test_add_persists_without_committing_the_request_transaction() -> None:
    asset = make_asset()
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = SqlAlchemyImageAssetRepository(session)

    result = await repository.add(asset)

    assert result is asset
    session.add.assert_called_once_with(asset)
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_owned_filters_by_asset_user_and_soft_delete() -> None:
    asset = make_asset()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=asset)
    repository = SqlAlchemyImageAssetRepository(session)

    result = await repository.get_owned(
        user_id=asset.user_id,
        asset_id=asset.id,
    )

    assert result is asset
    sql = compile_statement(session.scalar.await_args.args[0])
    assert f"image_assets.id = '{asset.id}'" in sql
    assert f"image_assets.user_id = '{asset.user_id}'" in sql
    assert "image_assets.deleted_at IS NULL" in sql
    assert "FOR UPDATE" not in sql


@pytest.mark.asyncio
async def test_get_owned_can_lock_the_asset_during_state_transition() -> None:
    asset = make_asset()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=asset)
    repository = SqlAlchemyImageAssetRepository(session)

    await repository.get_owned(
        user_id=asset.user_id,
        asset_id=asset.id,
        lock=True,
    )

    sql = compile_statement(session.scalar.await_args.args[0])
    assert "FOR UPDATE" in sql
    assert f"image_assets.user_id = '{asset.user_id}'" in sql


@pytest.mark.asyncio
async def test_get_owned_only_includes_deleted_assets_when_explicitly_requested() -> None:
    asset = make_asset()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=asset)
    repository = SqlAlchemyImageAssetRepository(session)

    await repository.get_owned(
        user_id=asset.user_id,
        asset_id=asset.id,
        include_deleted=True,
    )

    sql = compile_statement(session.scalar.await_args.args[0])
    assert "image_assets.deleted_at IS NULL" not in sql
    assert f"image_assets.user_id = '{asset.user_id}'" in sql


@pytest.mark.asyncio
async def test_save_flushes_state_changes_without_committing() -> None:
    asset = make_asset()
    asset.status = "ready"
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repository = SqlAlchemyImageAssetRepository(session)

    result = await repository.save(asset)

    assert result is asset
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_expired_pending_claims_rows_safely_for_cleanup_workers() -> None:
    asset = make_asset()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [asset]
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=scalar_result)
    repository = SqlAlchemyImageAssetRepository(session)
    now = datetime.now(UTC)

    result = await repository.list_expired_pending(now=now, limit=50)

    assert result == [asset]
    sql = compile_statement(session.scalars.await_args.args[0])
    assert "image_assets.status = 'pending_upload'" in sql
    assert "image_assets.upload_expires_at <=" in sql
    assert "image_assets.deleted_at IS NULL" in sql
    assert "ORDER BY image_assets.upload_expires_at, image_assets.id" in sql
    assert "LIMIT 50" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql


@pytest.mark.asyncio
async def test_list_expired_pending_rejects_invalid_batch_size() -> None:
    session = MagicMock(spec=AsyncSession)
    repository = SqlAlchemyImageAssetRepository(session)

    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await repository.list_expired_pending(
            now=datetime.now(UTC),
            limit=0,
        )
