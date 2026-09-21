from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, UniqueConstraint

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "fc07f60845fc_create_image_assets_table.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[tuple[str, tuple[Any, ...]]] = []
        self.created_indexes: list[tuple[str, str, tuple[str, ...], bool]] = []
        self.dropped_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []

    def f(self, name: str) -> str:
        return name

    def create_table(self, name: str, *elements: Any) -> None:
        self.created_tables.append((name, elements))

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool,
    ) -> None:
        self.created_indexes.append((name, table_name, tuple(columns), unique))

    def drop_index(self, name: str, *, table_name: str) -> None:
        self.dropped_indexes.append((name, table_name))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def load_migration() -> ModuleType:
    spec = spec_from_file_location("media_asset_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_media_migration_extends_the_expected_revision() -> None:
    migration = load_migration()

    assert migration.revision == "fc07f60845fc"
    assert migration.down_revision == "9a31c6d82f44"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_media_migration_upgrade_creates_only_private_image_assets() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert len(operations.created_tables) == 1
    table_name, elements = operations.created_tables[0]
    assert table_name == "image_assets"

    columns = {element.name: element for element in elements if isinstance(element, Column)}
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
    } == set(columns)
    assert "public_url" not in columns
    assert columns["status"].server_default.arg == "pending_upload"

    foreign_keys = [element for element in elements if isinstance(element, ForeignKeyConstraint)]
    assert len(foreign_keys) == 1
    assert foreign_keys[0].ondelete == "CASCADE"
    assert tuple(foreign_keys[0].elements)[0].target_fullname == "users.id"

    unique_constraints = [element for element in elements if isinstance(element, UniqueConstraint)]
    assert {constraint.name for constraint in unique_constraints} == {"uq_image_assets_object_key"}
    assert set(operations.created_indexes) == {
        (
            "ix_image_assets_status_upload_expiry",
            "image_assets",
            ("status", "upload_expires_at"),
            False,
        ),
        (
            "ix_image_assets_user_created",
            "image_assets",
            ("user_id", "created_at"),
            False,
        ),
    }


def test_media_migration_downgrade_removes_only_its_own_objects() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert set(operations.dropped_indexes) == {
        ("ix_image_assets_user_created", "image_assets"),
        ("ix_image_assets_status_upload_expiry", "image_assets"),
    }
    assert operations.dropped_tables == ["image_assets"]
