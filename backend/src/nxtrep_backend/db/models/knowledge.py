from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from nxtrep_backend.db.base import Base, IdMixin, TimestampMixin

KNOWLEDGE_EMBEDDING_DIMENSIONS = 1024


class KnowledgeSource(IdMixin, TimestampMixin, Base):
    """An administrator-managed origin for shared, reviewed knowledge."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('manual', 'file', 'url')",
            name="source_type",
        ),
        CheckConstraint(
            "length(btrim(source_key)) > 0",
            name="source_key_not_blank",
        ),
        CheckConstraint(
            "source_key = lower(source_key)",
            name="source_key_lowercase",
        ),
        CheckConstraint(
            "topic IN ('exercise', 'training', 'nutrition', 'product_help', 'safety')",
            name="topic",
        ),
        CheckConstraint(
            "ingest_status IN ('pending', 'processing', 'ready', 'failed')",
            name="ingest_status",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(btrim(locale)) > 0", name="locale_not_blank"),
        CheckConstraint(
            "source_type = 'manual' OR (source_uri IS NOT NULL AND length(btrim(source_uri)) > 0)",
            name="uri_required",
        ),
        CheckConstraint(
            "NOT is_active OR ingest_status = 'ready'",
            name="active_requires_ready",
        ),
        CheckConstraint("latest_version >= 0", name="latest_version_non_negative"),
        UniqueConstraint(
            "source_key",
            name="uq_knowledge_sources_source_key",
        ),
        Index(
            "ix_knowledge_sources_retrieval_scope",
            "is_active",
            "ingest_status",
            "topic",
            "locale",
        ),
    )

    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(200))
    license_name: Mapped[str | None] = mapped_column(String(120))
    topic: Mapped[str] = mapped_column(String(30), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="zh-CN")
    ingest_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    latest_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(1000))


class KnowledgeDocument(IdMixin, TimestampMixin, Base):
    """One immutable normalized version imported from a knowledge source."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("source_version >= 1", name="source_version_positive"),
        CheckConstraint(
            "topic IN ('exercise', 'training', 'nutrition', 'product_help', 'safety')",
            name="topic",
        ),
        CheckConstraint(
            "review_status IN ('draft', 'reviewed', 'published', 'archived')",
            name="review_status",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "length(btrim(normalized_content)) > 0",
            name="normalized_content_not_blank",
        ),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256"),
        CheckConstraint("length(btrim(locale)) > 0", name="locale_not_blank"),
        CheckConstraint(
            "review_status <> 'published' OR published_at IS NOT NULL",
            name="published_at_required",
        ),
        UniqueConstraint(
            "source_id",
            "source_version",
            name="uq_knowledge_documents_source_version",
        ),
        Index(
            "ix_knowledge_documents_retrieval_scope",
            "review_status",
            "topic",
            "locale",
        ),
    )

    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(String(30), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class KnowledgeChunk(IdMixin, TimestampMixin, Base):
    """A searchable section of one immutable knowledge document."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256"),
        CheckConstraint("length(btrim(search_text)) > 0", name="search_text_not_blank"),
        UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_knowledge_chunks_document_ordinal",
        ),
        Index(
            "ix_knowledge_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', search_text)", persisted=True),
        nullable=False,
    )


class KnowledgeEmbedding(IdMixin, TimestampMixin, Base):
    """A model-specific vector representation of one knowledge chunk."""

    __tablename__ = "knowledge_embeddings"
    __table_args__ = (
        CheckConstraint(
            f"dimensions = {KNOWLEDGE_EMBEDDING_DIMENSIONS}",
            name="dimensions",
        ),
        CheckConstraint("length(btrim(model_name)) > 0", name="model_name_not_blank"),
        CheckConstraint("length(btrim(model_version)) > 0", name="model_version_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256"),
        UniqueConstraint(
            "chunk_id",
            "model_name",
            "model_version",
            "dimensions",
            name="uq_knowledge_embeddings_chunk_model_version_dimensions",
        ),
        Index(
            "ix_knowledge_embeddings_model_scope",
            "model_name",
            "model_version",
            "dimensions",
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=KNOWLEDGE_EMBEDDING_DIMENSIONS,
        server_default=text(str(KNOWLEDGE_EMBEDDING_DIMENSIONS)),
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(KNOWLEDGE_EMBEDDING_DIMENSIONS),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
