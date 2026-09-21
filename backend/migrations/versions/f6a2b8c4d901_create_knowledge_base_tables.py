"""create knowledge base tables

Revision ID: f6a2b8c4d901
Revises: c91e5a7d24b0
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "f6a2b8c4d901"
down_revision: str | Sequence[str] | None = "c91e5a7d24b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector is infrastructure provisioned by a database administrator.  The
    # application migration checks for it and fails with an actionable message
    # instead of trying to acquire superuser privileges.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_extension WHERE extname = 'vector'
            ) THEN
                RAISE EXCEPTION
                    'pgvector extension is required before running this migration'
                    USING HINT = 'Run CREATE EXTENSION vector as a database administrator.';
            END IF;
        END
        $$;
        """
    )

    op.create_table(
        "knowledge_sources",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("license_name", sa.String(length=120), nullable=True),
        sa.Column("topic", sa.String(length=30), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column(
            "ingest_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "latest_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'file', 'url')",
            name=op.f("ck_knowledge_sources_source_type"),
        ),
        sa.CheckConstraint(
            "topic IN ('exercise', 'training', 'nutrition', 'product_help', 'safety')",
            name=op.f("ck_knowledge_sources_topic"),
        ),
        sa.CheckConstraint(
            "ingest_status IN ('pending', 'processing', 'ready', 'failed')",
            name=op.f("ck_knowledge_sources_ingest_status"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name=op.f("ck_knowledge_sources_title_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(locale)) > 0",
            name=op.f("ck_knowledge_sources_locale_not_blank"),
        ),
        sa.CheckConstraint(
            "source_type = 'manual' OR (source_uri IS NOT NULL AND length(btrim(source_uri)) > 0)",
            name=op.f("ck_knowledge_sources_uri_required"),
        ),
        sa.CheckConstraint(
            "NOT is_active OR ingest_status = 'ready'",
            name=op.f("ck_knowledge_sources_active_requires_ready"),
        ),
        sa.CheckConstraint(
            "latest_version >= 0",
            name=op.f("ck_knowledge_sources_latest_version_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
    )
    op.create_index(
        "ix_knowledge_sources_retrieval_scope",
        "knowledge_sources",
        ["is_active", "ingest_status", "topic", "locale"],
        unique=False,
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=30), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_version >= 1",
            name=op.f("ck_knowledge_documents_source_version_positive"),
        ),
        sa.CheckConstraint(
            "topic IN ('exercise', 'training', 'nutrition', 'product_help', 'safety')",
            name=op.f("ck_knowledge_documents_topic"),
        ),
        sa.CheckConstraint(
            "review_status IN ('draft', 'reviewed', 'published', 'archived')",
            name=op.f("ck_knowledge_documents_review_status"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name=op.f("ck_knowledge_documents_title_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_content)) > 0",
            name=op.f("ck_knowledge_documents_normalized_content_not_blank"),
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name=op.f("ck_knowledge_documents_content_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(btrim(locale)) > 0",
            name=op.f("ck_knowledge_documents_locale_not_blank"),
        ),
        sa.CheckConstraint(
            "review_status <> 'published' OR published_at IS NOT NULL",
            name=op.f("ck_knowledge_documents_published_at_required"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.id"],
            name=op.f("fk_knowledge_documents_source_id_knowledge_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
        sa.UniqueConstraint(
            "source_id",
            "source_version",
            name=op.f("uq_knowledge_documents_source_version"),
        ),
    )
    op.create_index(
        op.f("ix_knowledge_documents_source_id"),
        "knowledge_documents",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_documents_retrieval_scope",
        "knowledge_documents",
        ["review_status", "topic", "locale"],
        unique=False,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(length=500), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', search_text)", persisted=True),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_knowledge_chunks_ordinal_non_negative"),
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name=op.f("ck_knowledge_chunks_token_count_positive"),
        ),
        sa.CheckConstraint(
            "length(btrim(content)) > 0",
            name=op.f("ck_knowledge_chunks_content_not_blank"),
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name=op.f("ck_knowledge_chunks_content_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(btrim(search_text)) > 0",
            name=op.f("ck_knowledge_chunks_search_text_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_chunks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name=op.f("uq_knowledge_chunks_document_ordinal"),
        ),
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_id"),
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_search_vector",
        "knowledge_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_table(
        "knowledge_embeddings",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column(
            "dimensions",
            sa.Integer(),
            server_default=sa.text("1024"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(dim=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimensions = 1024",
            name=op.f("ck_knowledge_embeddings_dimensions"),
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) > 0",
            name=op.f("ck_knowledge_embeddings_model_name_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(model_version)) > 0",
            name=op.f("ck_knowledge_embeddings_model_version_not_blank"),
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name=op.f("ck_knowledge_embeddings_content_hash_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.id"],
            name=op.f("fk_knowledge_embeddings_chunk_id_knowledge_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_embeddings")),
        sa.UniqueConstraint(
            "chunk_id",
            "model_name",
            "model_version",
            "dimensions",
            name=op.f("uq_knowledge_embeddings_chunk_model_version_dimensions"),
        ),
    )
    op.create_index(
        op.f("ix_knowledge_embeddings_chunk_id"),
        "knowledge_embeddings",
        ["chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_embeddings_model_scope",
        "knowledge_embeddings",
        ["model_name", "model_version", "dimensions"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_embeddings_model_scope",
        table_name="knowledge_embeddings",
    )
    op.drop_index(
        op.f("ix_knowledge_embeddings_chunk_id"),
        table_name="knowledge_embeddings",
    )
    op.drop_table("knowledge_embeddings")

    op.drop_index(
        "ix_knowledge_chunks_search_vector",
        table_name="knowledge_chunks",
        postgresql_using="gin",
    )
    op.drop_index(
        op.f("ix_knowledge_chunks_document_id"),
        table_name="knowledge_chunks",
    )
    op.drop_table("knowledge_chunks")

    op.drop_index(
        "ix_knowledge_documents_retrieval_scope",
        table_name="knowledge_documents",
    )
    op.drop_index(
        op.f("ix_knowledge_documents_source_id"),
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")

    op.drop_index(
        "ix_knowledge_sources_retrieval_scope",
        table_name="knowledge_sources",
    )
    op.drop_table("knowledge_sources")
