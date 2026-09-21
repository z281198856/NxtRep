from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, ForeignKeyConstraint, UniqueConstraint

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "f6a2b8c4d901_create_knowledge_base_tables.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.created_tables: list[tuple[str, tuple[Any, ...]]] = []
        self.created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = []
        self.dropped_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []

    def f(self, name: str) -> str:
        return name

    def execute(self, statement: str) -> None:
        self.executed_sql.append(statement)

    def create_table(self, name: str, *elements: Any) -> None:
        self.created_tables.append((name, elements))

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        **options: Any,
    ) -> None:
        self.created_indexes.append((name, table_name, tuple(columns), options))

    def drop_index(self, name: str, *, table_name: str, **options: Any) -> None:
        self.dropped_indexes.append((name, table_name))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def load_migration() -> ModuleType:
    spec = spec_from_file_location("knowledge_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_knowledge_migration_extends_current_revision() -> None:
    migration = load_migration()

    assert migration.revision == "f6a2b8c4d901"
    assert migration.down_revision == "c91e5a7d24b0"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_knowledge_migration_checks_pgvector_and_creates_hierarchy() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    sql = " ".join(" ".join(operations.executed_sql).split()).lower()
    assert "from pg_extension" in sql
    assert "extname = 'vector'" in sql
    assert "create extension vector;" not in sql
    assert [name for name, _ in operations.created_tables] == [
        "knowledge_sources",
        "knowledge_documents",
        "knowledge_chunks",
        "knowledge_embeddings",
    ]

    table_elements = dict(operations.created_tables)
    document_foreign_key = next(
        element
        for element in table_elements["knowledge_documents"]
        if isinstance(element, ForeignKeyConstraint)
    )
    chunk_foreign_key = next(
        element
        for element in table_elements["knowledge_chunks"]
        if isinstance(element, ForeignKeyConstraint)
    )
    embedding_foreign_key = next(
        element
        for element in table_elements["knowledge_embeddings"]
        if isinstance(element, ForeignKeyConstraint)
    )
    assert document_foreign_key.ondelete == "CASCADE"
    assert chunk_foreign_key.ondelete == "CASCADE"
    assert embedding_foreign_key.ondelete == "CASCADE"


def test_knowledge_migration_creates_generated_search_and_vector_columns() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations
    migration.upgrade()
    table_elements = dict(operations.created_tables)

    chunk_columns = {
        element.name: element
        for element in table_elements["knowledge_chunks"]
        if isinstance(element, Column)
    }
    computed = chunk_columns["search_vector"].computed
    assert isinstance(computed, Computed)
    assert str(computed.sqltext) == "to_tsvector('simple', search_text)"
    assert computed.persisted is True

    embedding_columns = {
        element.name: element
        for element in table_elements["knowledge_embeddings"]
        if isinstance(element, Column)
    }
    assert isinstance(embedding_columns["embedding"].type, Vector)
    assert embedding_columns["embedding"].type.dim == 1024

    embedding_unique = {
        element.name
        for element in table_elements["knowledge_embeddings"]
        if isinstance(element, UniqueConstraint)
    }
    assert "uq_knowledge_embeddings_chunk_model_version_dimensions" in embedding_unique
    assert any(
        name == "ix_knowledge_chunks_search_vector" and options.get("postgresql_using") == "gin"
        for name, _, _, options in operations.created_indexes
    )


def test_knowledge_migration_downgrade_preserves_pgvector_infrastructure() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    assert operations.dropped_tables == [
        "knowledge_embeddings",
        "knowledge_chunks",
        "knowledge_documents",
        "knowledge_sources",
    ]
    assert operations.executed_sql == []
