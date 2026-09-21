from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import Column, String

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "0f4d9a6c2b73_add_knowledge_source_key.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def f(self, name: str) -> str:
        return name

    def add_column(self, table: str, column: Column) -> None:
        self.calls.append(("add_column", (table, column), {}))

    def execute(self, statement: str) -> None:
        self.calls.append(("execute", (statement,), {}))

    def alter_column(self, table: str, column: str, **options: Any) -> None:
        self.calls.append(("alter_column", (table, column), options))

    def create_check_constraint(
        self,
        name: str,
        table: str,
        condition: str,
    ) -> None:
        self.calls.append(
            ("create_check_constraint", (name, table, condition), {})
        )

    def create_unique_constraint(
        self,
        name: str,
        table: str,
        columns: list[str],
    ) -> None:
        self.calls.append(
            ("create_unique_constraint", (name, table, tuple(columns)), {})
        )

    def drop_constraint(
        self,
        name: str,
        table: str,
        **options: Any,
    ) -> None:
        self.calls.append(("drop_constraint", (name, table), options))

    def drop_column(self, table: str, column: str) -> None:
        self.calls.append(("drop_column", (table, column), {}))


def load_migration() -> ModuleType:
    spec = spec_from_file_location("knowledge_source_key_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_key_migration_extends_knowledge_tables_revision() -> None:
    migration = load_migration()

    assert migration.revision == "0f4d9a6c2b73"
    assert migration.down_revision == "f6a2b8c4d901"


def test_source_key_migration_backfills_before_constraints() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    assert [name for name, _, _ in operations.calls] == [
        "add_column",
        "execute",
        "alter_column",
        "create_check_constraint",
        "create_check_constraint",
        "create_unique_constraint",
    ]
    added_column = operations.calls[0][1][1]
    assert isinstance(added_column, Column)
    assert added_column.name == "source_key"
    assert isinstance(added_column.type, String)
    assert added_column.type.length == 120
    assert added_column.nullable is True
    backfill_sql = " ".join(operations.calls[1][1][0].split()).lower()
    assert "legacy-" in backfill_sql
    assert "where source_key is null" in backfill_sql
    assert operations.calls[2][2]["nullable"] is False
    constraint_names = {
        arguments[0]
        for name, arguments, _ in operations.calls
        if name in {"create_check_constraint", "create_unique_constraint"}
    }
    assert constraint_names == {
        "ck_knowledge_sources_source_key_not_blank",
        "ck_knowledge_sources_source_key_lowercase",
        "uq_knowledge_sources_source_key",
    }


def test_source_key_migration_downgrade_removes_constraints_and_column() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert [name for name, _, _ in operations.calls] == [
        "drop_constraint",
        "drop_constraint",
        "drop_constraint",
        "drop_column",
    ]
    assert operations.calls[-1][1] == ("knowledge_sources", "source_key")
