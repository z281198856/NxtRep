from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR

from nxtrep_backend.db.base import Base
from nxtrep_backend.db.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSource,
)


def _constraint_names(model: type[object], constraint_type: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type)
    }


def test_knowledge_tables_are_registered_with_clear_responsibilities() -> None:
    assert {
        "knowledge_sources",
        "knowledge_documents",
        "knowledge_chunks",
        "knowledge_embeddings",
    } <= set(Base.metadata.tables)
    assert {
        "source_key",
        "title",
        "source_type",
        "source_uri",
        "topic",
        "locale",
        "ingest_status",
        "is_active",
        "latest_version",
    } <= set(KnowledgeSource.__table__.c.keys())
    assert {
        "source_id",
        "source_version",
        "normalized_content",
        "content_hash",
        "review_status",
    } <= set(KnowledgeDocument.__table__.c.keys())
    assert {"document_id", "ordinal", "content", "search_text", "search_vector"} <= set(
        KnowledgeChunk.__table__.c.keys()
    )
    assert {"chunk_id", "model_name", "model_version", "dimensions", "embedding"} <= set(
        KnowledgeEmbedding.__table__.c.keys()
    )


def test_knowledge_hierarchy_uses_cascade_foreign_keys() -> None:
    hierarchy = (
        (KnowledgeDocument, "source_id", "knowledge_sources.id"),
        (KnowledgeChunk, "document_id", "knowledge_documents.id"),
        (KnowledgeEmbedding, "chunk_id", "knowledge_chunks.id"),
    )

    for model, column_name, target in hierarchy:
        foreign_key = next(iter(model.__table__.c[column_name].foreign_keys))
        assert foreign_key.target_fullname == target
        assert foreign_key.ondelete == "CASCADE"


def test_knowledge_models_enforce_versions_order_and_embedding_identity() -> None:
    assert "uq_knowledge_sources_source_key" in _constraint_names(
        KnowledgeSource,
        UniqueConstraint,
    )
    assert "uq_knowledge_documents_source_version" in _constraint_names(
        KnowledgeDocument, UniqueConstraint
    )
    assert "uq_knowledge_chunks_document_ordinal" in _constraint_names(
        KnowledgeChunk, UniqueConstraint
    )
    assert "uq_knowledge_embeddings_chunk_model_version_dimensions" in _constraint_names(
        KnowledgeEmbedding, UniqueConstraint
    )

    check_names = (
        _constraint_names(KnowledgeSource, CheckConstraint)
        | _constraint_names(KnowledgeDocument, CheckConstraint)
        | _constraint_names(KnowledgeChunk, CheckConstraint)
        | _constraint_names(KnowledgeEmbedding, CheckConstraint)
    )
    assert {
        "ck_knowledge_sources_source_key_not_blank",
        "ck_knowledge_sources_source_key_lowercase",
        "ck_knowledge_sources_active_requires_ready",
        "ck_knowledge_documents_published_at_required",
        "ck_knowledge_chunks_token_count_positive",
        "ck_knowledge_embeddings_dimensions",
    } <= check_names


def test_knowledge_chunk_has_generated_postgres_full_text_search_column() -> None:
    column = KnowledgeChunk.__table__.c.search_vector

    assert isinstance(column.type, TSVECTOR)
    assert isinstance(column.computed, Computed)
    assert str(column.computed.sqltext) == "to_tsvector('simple', search_text)"
    assert column.computed.persisted is True

    search_index = next(
        index
        for index in KnowledgeChunk.__table__.indexes
        if index.name == "ix_knowledge_chunks_search_vector"
    )
    assert search_index.dialect_options["postgresql"]["using"] == "gin"


def test_knowledge_embedding_is_fixed_to_the_configured_dimension() -> None:
    embedding_type = KnowledgeEmbedding.__table__.c.embedding.type

    assert isinstance(embedding_type, Vector)
    assert embedding_type.dim == 1024
    assert KnowledgeEmbedding.__table__.c.dimensions.server_default.arg.text == "1024"
