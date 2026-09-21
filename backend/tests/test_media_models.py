from sqlalchemy import BigInteger, DateTime, UniqueConstraint

from nxtrep_backend.db.base import Base
from nxtrep_backend.db.models import ImageAsset


def test_image_asset_table_is_registered_with_required_columns() -> None:
    assert ImageAsset.__tablename__ == "image_assets"
    assert "image_assets" in Base.metadata.tables
    assert {
        "id",
        "user_id",
        "purpose",
        "object_key",
        "content_type",
        "content_length",
        "status",
        "upload_expires_at",
        "etag",
        "completed_at",
        "failure_reason",
        "deleted_at",
        "created_at",
        "updated_at",
    } <= set(ImageAsset.__table__.c.keys())


def test_image_asset_is_owned_by_a_user_and_cascades_on_user_delete() -> None:
    user_id = ImageAsset.__table__.c.user_id
    user_foreign_key = next(iter(user_id.foreign_keys))

    assert user_id.nullable is False
    assert user_foreign_key.target_fullname == "users.id"
    assert user_foreign_key.ondelete == "CASCADE"


def test_image_asset_keeps_private_storage_identity_only() -> None:
    table = ImageAsset.__table__
    unique_constraint_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_image_assets_object_key" in unique_constraint_names
    assert table.c.object_key.nullable is False
    assert "public_url" not in table.c
    assert "upload_url" not in table.c


def test_image_asset_has_database_safety_constraints() -> None:
    constraint_names = {constraint.name for constraint in ImageAsset.__table__.constraints}

    assert {
        "ck_image_assets_purpose",
        "ck_image_assets_content_type",
        "ck_image_assets_content_length_positive",
        "ck_image_assets_status",
        "ck_image_assets_object_key_not_blank",
    } <= constraint_names


def test_image_asset_starts_in_pending_upload_status() -> None:
    status = ImageAsset.__table__.c.status

    assert status.nullable is False
    assert status.default.arg == "pending_upload"
    assert status.server_default.arg == "pending_upload"


def test_image_asset_supports_large_object_metadata_and_timezone_aware_events() -> None:
    table = ImageAsset.__table__

    assert isinstance(table.c.content_length.type, BigInteger)
    assert table.c.content_length.nullable is False
    assert table.c.upload_expires_at.nullable is False
    for column_name in (
        "upload_expires_at",
        "completed_at",
        "deleted_at",
        "created_at",
        "updated_at",
    ):
        column_type = table.c[column_name].type
        assert isinstance(column_type, DateTime)
        assert column_type.timezone is True


def test_image_asset_has_user_listing_and_expired_upload_cleanup_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in ImageAsset.__table__.indexes
    }

    assert indexes["ix_image_assets_user_created"] == ("user_id", "created_at")
    assert indexes["ix_image_assets_status_upload_expiry"] == (
        "status",
        "upload_expires_at",
    )


def test_image_asset_processing_result_fields_are_optional() -> None:
    table = ImageAsset.__table__

    assert table.c.etag.nullable is True
    assert table.c.completed_at.nullable is True
    assert table.c.failure_reason.nullable is True
    assert table.c.deleted_at.nullable is True
