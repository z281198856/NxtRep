from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from nxtrep_backend.schemas.auth import UsernameRequest


class AdminUserCreateRequest(UsernameRequest):
    display_name: str | None = Field(default=None, max_length=80)
    is_admin: bool = False

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value


class AdminUserCreateResponse(BaseModel):
    id: UUID
    username: str
    display_name: str | None
    is_admin: bool
    password_setup_required: bool
    setup_token: str = Field(min_length=32)
    setup_token_expires_at: datetime


KnowledgeTopic = Literal["exercise", "training", "nutrition", "product_help", "safety"]


class KnowledgeSourceCreateRequest(BaseModel):
    source_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    source_type: Literal["manual", "file", "url"]
    source_uri: str | None = None
    publisher: str | None = Field(default=None, max_length=200)
    license_name: str | None = Field(default=None, max_length=120)
    topic: KnowledgeTopic
    locale: str = Field(default="zh-CN", min_length=1, max_length=20)
    metadata: dict = Field(default_factory=dict)


class KnowledgeSourceResponse(BaseModel):
    id: UUID
    source_key: str
    title: str
    source_type: str
    source_uri: str | None
    publisher: str | None
    license_name: str | None
    topic: str
    locale: str
    ingest_status: str
    is_active: bool
    latest_version: int
    metadata_json: dict
    last_ingested_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None


class KnowledgeIngestRequest(BaseModel):
    path: Path
    content_type: Literal["application/pdf", "text/html"]


class KnowledgeIngestResponse(BaseModel):
    status: str
    source_id: UUID
    document_id: UUID
    source_version: int
    created_chunks: int
    created_embeddings: int


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    source_id: UUID
    source_version: int
    title: str
    topic: str
    locale: str
    review_status: str
    published_at: datetime | None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    topic: KnowledgeTopic
    locale: str = Field(default="zh-CN", min_length=1, max_length=20)
    candidate_k: int = Field(default=20, ge=1, le=100)
    top_k: int = Field(default=5, ge=1, le=10)
    source_keys: list[str] = Field(default_factory=list, max_length=50)


class KnowledgeSearchHitResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    source_key: str
    source_title: str
    source_uri: str | None
    source_version: int
    topic: str
    locale: str
    content: str
    section_path: str | None
    page_numbers: list[int]
    score: float
    match_type: str
    metadata: dict


class AdminJobResponse(BaseModel):
    id: UUID
    job_type: Literal["knowledge_ingestion"] = "knowledge_ingestion"
    status: str
    source_key: str
    error_code: str | None
    error_message: str | None
    updated_at: datetime
